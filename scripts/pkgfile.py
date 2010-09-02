#!/usr/bin/python
###
# pkgfile.py -- search the arch repo to see what package owns a file
# This program is a part of pkgtools

# Copyright (C) 2008-2010 Daenyth <Daenyth+Arch _AT_ gmail _DOT_ com>
# Copyright (C) 2010 solsTiCe d'Hiver <solstice.dhiver@gmail.com>
#
# Pkgtools is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# Pkgtools is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
##

from sys import exit, stderr
from os.path import exists, join
from os import unlink, getpid, listdir, getenv, umask
from optparse import OptionParser, OptionGroup
import signal
from subprocess import Popen, PIPE
import re
from urllib import urlretrieve
from alpm2sqlite import convert, open_db, update_repo_from_dir

server = re.compile(r'.*adding new server URL to database \'(.*)\': (.*)')

VERSION = '22'
CONFIG_DIR = '/etc/pkgtools'
FILELIST_DIR = '/usr/share/pkgtools'
LOCKFILE = '/var/lock/pkgfile'

def find_dbpath():
    '''find pacman dbpath'''
    p = Popen(['pacman', '-v'], stdout=PIPE)
    output = p.communicate()[0]
    for line in output.split('\n'):
        if line.startswith('DB Path'):
            return line.split(':')[1].strip()

def parse_config(filename, comment_char='#', option_char='='):
    # Borrowed at http://www.decalage.info/en/python/configparser
    # another option is http://mail.python.org/pipermail/python-dev/2002-November/029987.html
    options = {}
    try:
        f = open(filename)
        for line in f:
            line = line.strip()
            if comment_char in line:
                line, comment = line.split(comment_char, 1)
            if option_char in line:
                option, value = line.split(option_char, 1)
                option = option.strip()
                value = value.strip()
                try:
                    options[option] = int(value)
                except ValueError:
                    options[option] = value
        f.close()
    except IOError:
        pass
    return options

def load_config(conf_file):
    options = parse_config(join(CONFIG_DIR, conf_file))
    XDG_CONFIG_HOME = getenv('XDG_CONFIG_HOME')
    xdg_conf_file = join(XDG_CONFIG_HOME, 'pkgtools', conf_file)
    if exists(xdg_conf_file):
        tmp = parse_config(xdg_conf_file)
        for k in tmp:
            options[k] = tmp[k]
    # NOT IMPLEMENTED: ${HOME}/.pkgtools/pkgfile.conf.
    # We could say it's depreciated and obsolete
    return options

def die(n=-1, msg='Unknown error'):
    print >> stderr, msg
    exit(n)

def lock():
    if exists(LOCKFILE):
        die(1, 'Error: Unable to take lock at %s' % LOCKFILE)
    try:
        with open(LOCKFILE, 'w') as f:
            f.write('%d' % getpid())
    except IOError:
        die(1, 'Error: Unable to take lock at %s' % LOCKFILE)

def unlock():
    try:
        unlink(LOCKFILE)
    except OSError:
        print >> stderr, 'Warning: Failed to unlock %s' % LOCKFILE

def handle_SIGINT(signum, frame):
    unlock()
    die(1, 'Caught SIGINT -- aborting!')

def handle_SIGTERM(signum, frame):
    unlock()
    die(1, 'Killed!')

PKG_ATTRS = ('name', 'filename', 'version', 'desc', 'groups', 'url', 'license', 'arch',
        'builddate', 'installdate', 'packager', 'reason', 'isize', 'csize', 'md5sum',
        'replaces', 'force', 'depends', 'optdepends', 'conflicts',
        'provides', 'files', 'backup')
WIDTH = max(len(i) for i in PKG_ATTRS) + 1

def print_pkg(pkg):
    s = {}
    for p in PKG_ATTRS:
        ps = p.capitalize().ljust(WIDTH)
        try:
            prop = pkg[p]
        except KeyError:
            continue
        if prop is None:
            s[p] = '%s: --' % ps
            continue
        if p == 'csize' or p == 'isize':
            s[p] = '%s: %d k' % (ps, prop/1024)
        #elif p == 'force':
        #    s[p] = '%s: %d' % (ps, prop)
        elif p in ('groups', 'license', 'replaces',  'depends', 'optdepends', 'conflicts', 'provides'):
            s[p] = '%s: %s' % (ps, '  '.join(prop))
        elif p == 'backup':
            s[p] = ps+':'
            for i in prop:
                s[p] += '\n'+': '.join(i.split('\t')) +'\n'
            else:
                s[p] += ' --'
        #elif p == 'files':
        #    s[p] = '%s: %s' % (ps, '\n'+'\n'.join(prop))
        else:
            s[p] = '%s: %s' % (ps, prop)

    for i in ('name', 'filename', 'version', 'url', 'license', 'groups', 'provides',
            'depends', 'optdepends', 'conflicts', 'replaces', 'isize','packager',
            'arch', 'installdate', 'builddate', 'desc'):
        try:
            print s[i]
        except KeyError:
            pass
    print

def update(options, target_repo=None):
    signal.signal(signal.SIGINT, handle_SIGINT)
    signal.signal(signal.SIGTERM, handle_SIGTERM)

    lock()

    p = Popen(['pacman', '--debug'], stdout=PIPE)
    output = p.communicate()[0]

    # get a list of repo and mirror
    res = []
    for line in output.split('\n'):
        m = server.match(line)
        if m:
            res.append((m.group(1), m.group(2)))

    repo_done = []
    for repo, mirror in res:
        if target_repo is not None and repo != target_repo:
            continue
        if repo not in repo_done:
            print ':: Downloading [%s] file list ...' % repo
            repofile = '%s.files.tar.gz' % repo
            filelist = join(mirror, repofile)

            try:
                if options.verbose:
                    print 'Trying mirror %s ...' % mirror
                filename, headers = urlretrieve(filelist) # use a temp file
                print ':: Converting [%s] file list ...' % repo
                ret = convert(filename, '%s/%s.db' % (FILELIST_DIR, repo))
                unlink(filename)
                if not ret:
                    print >> stderr, 'Warning: Unable to extract %s' % filelist
                    continue

                repo_done.append(repo)
                print 'Done'
            except IOError:
                print >> stderr, 'Warning: could not retrieve %s' % filelist
                continue

    print ':: Converting local repo ...'
    local_db = '%s/local.db' % FILELIST_DIR
    local_dbpath = join(find_dbpath(), 'local')
    if exists(local_db):
        update_repo_from_dir(local_dbpath, local_db, options)
    else:
        convert(local_dbpath, local_db)
    print 'Done'

    unlock()

def list_files(s, options):
    repo = ''
    if '/' in s:
        res = s.split('/')
        if len(res) > 2:
            print >> stderr, 'If given foo/bar, assume "bar" package in "foo" repo'
            return
        repo, pkg = res
    else:
        pkg = s

    sql_stmt, search = ('select name,files from pkg where name=?' , (pkg,))
    if options.glob:
        sql_stmt, search = ('select name,files from pkg where name like ?' , (pkg.replace('*', '%').replace('?', '_'),))

    res = []
    if not options.remote and repo == '':
        conn, cur = open_db(join(FILELIST_DIR, 'local.db'))
        rows = cur.execute(sql_stmt, search)
        matches = rows.fetchmany()
        while matches:
            for pkg, files in matches:
                for f in files :
                    if options.binaries:
                        if '/sbin/' in f or '/bin/' in f:
                            res.append('%s /%s' % (pkg, f))
                    else:
                        res.append('%s /%s' % (pkg, f))
            res.sort()
            matches = rows.fetchmany()

        cur.close()
        conn.close()

    if res != []:
        print '\n'.join(res)
        return

    repo_list = listdir(FILELIST_DIR)
    del repo_list[repo_list.index('local.db')]
    for dbfile in repo_list:
        if repo != '' and repo != dbfile.replace('.db', ''):
            continue
        conn, cur = open_db(join(FILELIST_DIR, dbfile))
        rows = cur.execute(sql_stmt, search)
        matches = rows.fetchmany()
        while matches:
            for pkg, files in matches:
                for f in files:
                    if options.binaries:
                        if '/sbin/' in f or '/bin/' in f:
                            res.append('%s /%s' % (pkg, f))
                    else:
                        res.append('%s /%s' % (pkg, f))
            res.sort()
            matches = rows.fetchmany()

        cur.close()
        conn.close()

    if res == []:
        print 'Package "%s" not found' % pkg,
        if repo != '':
            print ' in repo %s' % repo,
        print
    else:
        print '\n'.join(res)

def pkgquery(filename, options):
    if options.glob:
        from fnmatch import translate
        regex = translate(filename)
    else:
        regex = filename
    if not options.case_sensitive:
        flags = re.IGNORECASE
    else:
        flags = 0 # case sensitive search by default
    try:
        filematch = re.compile(regex, flags)
    except re.error:
        die(1, 'Error: You need -g option to use * and ?')

    if exists(filename) and not options.remote:
        conn, cur = open_db('%s/local.db' % FILELIST_DIR)
        rows = cur.execute('select name,files from pkg')

        pkgfiles = rows.fetchmany()
        pkgname = ''
        # search the package name that have a filename
        while pkgfiles:
            for n,fls in pkgfiles:
                for f in fls:
                    if filematch.match('/'+f):
                        pkgname = n
                        break
            pkgfiles = rows.fetchmany()

        if pkgname == '':
            cur.close()
            conn.close()
            die(1, 'Unable to find package info for file %s' % filename)

        pkg = cur.execute('select * from pkg where name=?', (pkgname,)).fetchone()
        cur.close()
        conn.close()
        print_pkg(pkg)
        return

    # try in the other repo
    repo_list = listdir(FILELIST_DIR)
    del repo_list[repo_list.index('local.db')]
    pkgname = ''
    for dbfile in repo_list:
        conn, cur = open_db(join(FILELIST_DIR, dbfile))
        rows = cur.execute('select name,files from pkg')

        pkgfiles = rows.fetchmany()
        # search the package name that have a filename
        while pkgfiles and not pkgname:
            for n,fls in pkgfiles:
                for f in fls:
                    if filematch.match('/'+f):
                        pkgname = n
                        break
                if pkgname: break
            pkgfiles = rows.fetchmany()

        if pkgname: break
        # keep the conn alive if we have found a package
        cur.close()
        conn.close()

    if pkgname == '':
        die(1, 'Unable to find package info for file %s' % filename)

    pkg = cur.execute('select * from pkg where name=?', (pkgname,)).fetchone()
    cur.close()
    conn.close()
    print_pkg(pkg)

if __name__ == '__main__':
    usage = '%prog [ACTIONS] [OPTIONS] filename'
    parser = OptionParser(usage=usage, version='%%prog %s' % VERSION)
    # actions
    actions = OptionGroup(parser, 'ACTIONS')
    actions.add_option('-i', '--info', dest='info', action='store_true',
            default=False, help='provides information about the package owning a file')
    actions.add_option('-l', '--list', dest='list', action='store_true',
            default=False, help='list files of a given package; similar to "pacman -Ql"')
    actions.add_option('-s', '--search', dest='search', action='store_true',
            default=True, help='search which package owns a file')
    actions.add_option('-u', '--update', dest='update', action='store_true',
            default=False, help='update to the latest filelist. This requires write permission to %s' % FILELIST_DIR)
    parser.add_option_group(actions)

    # options
    parser.add_option('-b', '--binaries', dest='binaries', action='store_true',
            default=False, help='only show files in a {s}bin/ directory. Works with -s, -l')
    parser.add_option('-c', '--case-sensitive', dest='case_sensitive', action='store_true',
            default=False, help='make searches case sensitive')
    parser.add_option('-g', '--glob', dest='glob', action='store_true',
            default=False, help='allow the use of * and ? as wildcards')
    parser.add_option('-R', '--remote', dest='remote', action='store_true',
            default=False, help='exclude from the search the local pacman repository')
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
            default=False, help='enable verbose output')

    (options, args) = parser.parse_args()

    # This section is here for backward compatibilty but there is no need for it
    # TODO: trash this to the bin with load_config and parse_config
    dict_options = load_config('pkgfile.conf')
    try:
        FILELIST_DIR = dict_options['FILELIST_DIR']
    except KeyError:
        pass
    # PKGTOOLS_DIR is meaningless here
    # CONFIG_DIR is useless
    # RATELIMIT is not used (not implemented because wget is not used)
    # CMD_SEARCH_ENABLED is not used here
    # UPDATE_CRON neither 

    umask(0022) # This will ensure that any files we create are readable by normal users

    if options.update:
        try:
            update(options, target_repo=args[0])
        except IndexError:
            update(options)
    elif options.list:
        try:
            list_files(args[0], options)
        except IndexError:
            die(1, 'Error: No target specified to search for !')
    elif options.info:
        try:
            pkgquery(args[0], options)
        except IndexError:
            die(1, 'Error: No target specified to search for !')
