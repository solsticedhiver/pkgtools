#!/usr/bin/python
###
# pkgfile.py -- search the arch repo to see what package owns a file
# This program is a part of pkgtools
#
# Copyright (C) 2010 solsTiCe d'Hiver <solstice.dhiver@gmail.com>
#
# original bash version copyright was:
# Copyright (C) 2008-2010 Daenyth <Daenyth+Arch _AT_ gmail _DOT_ com>
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

import re
import glob
import os
import atexit
import sys
import optparse
import subprocess
import urllib2
import tarfile
import time
import pkgfile

VERSION = '22'
CONFIG_DIR = '/etc/pkgtools'
FILELIST_DIR = '/var/cache/pkgtools/lists'

def find_dbpath():
    '''find pacman dbpath'''

    p = subprocess.Popen(['pacman', '-v'], stdout=subprocess.PIPE)
    output = p.communicate()[0]
    for line in output.split('\n'):
        if line.startswith('DB Path'):
            return line.split(':')[1].strip()

def parse_config(filename, comment_char='#', option_char='='):
    '''basic function to parse a key=value config file'''
    # Borrowed at http://www.decalage.info/en/python/configparser
    # another option is http://mail.python.org/pipermail/python-dev/2002-November/029987.html

    options = {}
    try:
        with open(filename) as f:
            for line in f:
                line = line.strip()
                if comment_char in line:
                    line, comment = line.split(comment_char, 1)
                if option_char in line:
                    option, value = line.split(option_char, 1)
                    option = option.strip()
                    value = value.strip('"\' ')
                    try:
                        options[option] = int(value)
                    except ValueError:
                        options[option] = value
    except IOError:
        pass
    return options

def load_config(conf_file):
    '''load main config file and try in XDG_CONFIG_HOME too'''

    options = parse_config(os.path.join(CONFIG_DIR, conf_file))
    XDG_CONFIG_HOME = os.getenv('XDG_CONFIG_HOME')
    if  XDG_CONFIG_HOME is not None:
        xdg_conf_file = os.path.join(XDG_CONFIG_HOME, 'pkgtools', conf_file)
        if os.path.exists(xdg_conf_file):
            tmp = parse_config(xdg_conf_file)
            for k in tmp:
                options[k] = os.path.expanduser(tmp[k])
    return options

def die(n=-1, msg='Unknown error'):
    print >> sys.stderr, msg
    sys.exit(n)

# used below in print_pkg
PKG_ATTRS = ('name', 'filename', 'version', 'url', 'license', 'groups', 'provides',
            'depends', 'optdepends', 'conflicts', 'replaces', 'isize','packager',
            'arch', 'installdate', 'builddate', 'desc')
WIDTH = max(len(i) for i in PKG_ATTRS) + 1

def print_pkg(pkg):
    '''pretty print a pkg dict, mimicking pacman -Qi output'''

    # all attributes are not printed
    for p in PKG_ATTRS:
        field = p.capitalize().ljust(WIDTH)
        try:
            value = pkg[p]
        except KeyError:
            continue
        if value is None:
            print '%s: --' % field
            continue
        if p == 'csize' or p == 'isize':
            print '%s: %d k' % (field, value/1024)
        #elif p == 'force':
        #    print = '%s: %d' % (field, value)
        elif p in ('groups', 'license', 'replaces',  'depends', 'optdepends', 'conflicts', 'provides'):
            print '%s: %s' % (field, '  '.join(value))
        elif p == 'backup':
            s = field+':'
            for i in value:
                s += '\n'+': '.join(i.split('\t')) +'\n'
            else:
                s += ' --'
            print s
        #elif p == 'files':
        #    print '%s: %s' % (field, '\n'+'\n'.join(value))
        else:
            print '%s: %s' % (field, value)
    print

def update_repo(options, target_repo=None):
    '''download .files.tar.gz for each repo found in pacman config or the one specified'''

    if not os.path.exists(FILELIST_DIR):
        print >> sys.stderr, 'Warning: %s does not exist. Creating it.' % FILELIST_DIR
        try:
            os.mkdir(FILELIST_DIR, 0755)
        except OSError:
            die(1, 'Error: Can\'t create %s directory' % FILELIST_DIR)

    # check if FILELIST_DIR is writable
    if not os.access(FILELIST_DIR, os.F_OK|os.R_OK|os.W_OK|os.X_OK):
        die(1, 'Error: %s is not accessible' % FILELIST_DIR)

    p = subprocess.Popen(['pacman', '--debug'], stdout=subprocess.PIPE)
    output = p.communicate()[0]

    # get a list of repo and mirror
    res = []
    server = re.compile(r'.*adding new server URL to database \'(.*)\': (.*)')
    for line in output.split('\n'):
        m = server.match(line)
        if m:
            res.append((m.group(1), m.group(2)))

    repo_done = []
    for repo, mirror in res:
        if target_repo is not None and repo != target_repo:
            continue
        if repo not in repo_done:
            print ':: Checking [%s] for files list ...' % repo
            repofile = '%s.files.tar.gz' % repo
            fileslist = os.path.join(mirror, repofile)

            try:
                if options.verbose:
                    print 'Trying mirror %s ...' % mirror
                dbfile = '%s/%s.files.tar.gz' % (FILELIST_DIR, repo)
                try:
                    # try to get mtime of dbfile
                    local_mtime = os.path.getmtime(dbfile)
                except os.error:
                    local_mtime = 0 # fake a very old date if dbfile doesn't exist
                # Initiate connexion to get 'Last-Modified' header
                conn = urllib2.urlopen(fileslist)
                last_modified = conn.info().getdate('last-modified')
                if last_modified is None:
                    update = True
                    remote_mtime = time.time() # use current time instead
                else:
                    remote_mtime = time.mktime(last_modified)
                    update = remote_mtime > local_mtime

                if update or options.update > 1:
                    print ':: Downloading %s ...' % fileslist
                    # Saving data to local file
                    f = open(dbfile, 'w')
                    f.write(conn.read())
                    f.close()
                    conn.close()
                else:
                    print 'No update available'
                    conn.close()
                repo_done.append(repo)
            except IOError:
                print >> sys.stderr, 'Warning: could not retrieve %s' % fileslist
                continue

    local_db = os.path.join(FILELIST_DIR, 'local.files.tar.gz')

    if target_repo is None or target_repo == 'local':
        print ':: Converting local repo ...'
        local_dbpath = os.path.join(find_dbpath(), 'local')
        # create a tarball of local repo
        tf = tarfile.open(local_db, 'w:gz')
        cwd = os.getcwd() # save current working directory
        os.chdir(local_dbpath)
        tf.add('.')
        tf.close()
        os.chdir(cwd) # restore it
        print 'Done'

    # remove left-over db (for example for repo removed from pacman config)
    repos = glob.glob(os.path.join(FILELIST_DIR, '*.files.tar.gz'))
    registered_repos = set(os.path.join(FILELIST_DIR, r[0]+'.files.tar.gz') for r in res)
    registered_repos.add(local_db)
    for r in repos:
        if r not in registered_repos:
            print ':: Deleting %s' % r
            os.unlink(r)

def check_FILELIST_DIR():
    '''check if FILELIST_DIR exists and contais any *.files.tar.gz file'''

    if not os.path.exists(FILELIST_DIR):
        die(1, 'Error: %s does not exist. You might want to run "pkgfile -u" first.' % FILELIST_DIR)
    if len(glob.glob(os.path.join(FILELIST_DIR, '*.files.tar.gz'))) ==  0:
        die(1, 'Error: You need to run "pkgfile -u" first.')

def list_files(s, options):
    '''list files of package matching s'''

    check_FILELIST_DIR()

    target_repo = ''
    if '/' in s:
        res = s.split('/')
        if len(res) > 2:
            print >> sys.stderr, 'If given foo/bar, assume "bar" package in "foo" repo'
            return
        target_repo, pkg = res
    else:
        pkg = s

    res = []
    local_db = os.path.join(FILELIST_DIR, 'local.files.tar.gz')
    if options.local:
        repo_list = [local_db]
    else:
        repo_list = glob.glob(os.path.join(FILELIST_DIR, '*.files.tar.gz'))
        del repo_list[repo_list.index(local_db)]

    foundpkg = False
    for dbfile in repo_list:
        repo = os.path.basename(dbfile).replace('.files.tar.gz', '')
        if target_repo != '' and target_repo != repo:
            continue

        if options.regex:
            matches = pkgfile.list_regex(dbfile, s)
        else:
            matches = pkgfile.list(dbfile, s)

        for m in sorted(matches):
            for f in m['files']:
                if options.binaries:
                    if '/sbin/' in f or '/bin/' in f:
                        print '%s /%s' % (m['name'], f)
                        foundpkg = True
                else:
                    print '%s /%s' % (m['name'], f)
                    foundpkg = True

    if not foundpkg:
        print 'Package "%s" not found' % pkg,
        if target_repo != '':
            print ' in repo %s' % target_repo,
        print

def query_pkg(filename, options):
    '''search package with a file matching filename'''

    check_FILELIST_DIR()

    if options.glob:
        func = pkgfile.search_shell
    elif options.regex:
        func = pkgfile.search_regex
    else:
        func = pkgfile.search

    local_db = os.path.join(FILELIST_DIR, 'local.files.tar.gz')
    if os.path.exists(filename) or options.local:
        repo_list = [local_db]
    else:
        repo_list = glob.glob(os.path.join(FILELIST_DIR, '*.files.tar.gz'))
        del repo_list[repo_list.index(local_db)]

    for dbfile in repo_list:
        pkgfiles = func(dbfile, filename)
        repo = os.path.basename(dbfile).replace('.files.tar.gz', '')

        # search the package name that have a filename
        res = []
        for p in pkgfiles:
            matches = p['files']
            if options.binaries:
                matches = [f for f in p['files'] if '/sbin/' in f or '/bin/' in f]
            if matches != []:
                pkgname = '-'.join(p['package'].split('-')[:-2])
                pkgver = '-'.join(p['package'].split('-')[-2:])
                if options.info:
                    res.append((pkgname, matches))
                else:
                    if options.verbose:
                        print '\n'.join('%s/%s (%s) : /%s' % (repo, pkgname, pkgver, f) for f in matches)
                    else:
                        print '%s/%s' % (repo, pkgname)

        for n, fls in res:
            print "=== detailed info about pkg here ==="
            if options.verbose:
                print '\n'.join('%s/%s : /%s' % (repo, n, f) for f in fls) 
                print

def main():
    global FILELIST_DIR

    usage = '%prog [ACTIONS] [OPTIONS] filename'
    parser = optparse.OptionParser(usage=usage, version='%%prog %s' % VERSION)
    # actions
    actions = optparse.OptionGroup(parser, 'ACTIONS')
    actions.add_option('-i', '--info', dest='info', action='store_true',
            default=False, help='provides information about the package owning a file')
    actions.add_option('-l', '--list', dest='list', action='store_true',
            default=False, help='list files of a given package; similar to "pacman -Ql"')
    actions.add_option('-s', '--search', dest='search', action='store_true',
            default=True, help='search which package owns a file')
    actions.add_option('-u', '--update', dest='update', action='count',
            default=0, help='update to the latest filelist. This requires write permission to %s' % FILELIST_DIR)
    parser.add_option_group(actions)

    # options
    parser.add_option('-b', '--binaries', dest='binaries', action='store_true',
            default=False, help='only show files in a {s}bin/ directory. Works with -s, -l')
    parser.add_option('-c', '--case-sensitive', dest='case_sensitive', action='store_true',
            default=False, help='make searches case sensitive')
    parser.add_option('-g', '--glob', dest='glob', action='store_true',
            default=False, help='allow the use of * and ? as wildcards.')
    parser.add_option('-r', '--regex', dest='regex', action='store_true',
            default=False, help='allow the use of regex in searches')
    parser.add_option('-L', '--local', dest='local', action='store_true',
            default=False, help='search only in the local pacman repository')
    parser.add_option('-v', '--verbose', dest='verbose', action='store_true',
            default=False, help='enable verbose output')

    (options, args) = parser.parse_args()

    # This section is here for backward compatibility
    dict_options = load_config('pkgfile.conf')
    try:
        FILELIST_DIR = dict_options['FILELIST_DIR'].rstrip('/')
    except KeyError:
        pass
    # PKGTOOLS_DIR is meaningless here
    # CONFIG_DIR is useless
    # RATELIMIT is not used yet
    # options are:
    #   * use wget
    #   * make a throttling urlretrieve
    #   * use urlgrabber
    #   * use pycurl
    # CMD_SEARCH_ENABLED is not used here
    # UPDATE_CRON neither 

    if options.glob and options.regex:
        die(1, 'Error: -g/--glob and -r/--regex are exclusive.')

    if options.update:
        try:
            update_repo(options, target_repo=args[0])
        except IndexError:
            update_repo(options)
    elif options.list:
        try:
            list_files(args[0], options)
        except IndexError:
            die(1, 'Error: No target specified to search for !')
    elif options.info or options.search:
        try:
            query_pkg(args[0], options)
        except IndexError:
            die(1, 'Error: No target specified to search for !')

if __name__ == '__main__':
    # This will ensure that any files we create are readable by normal users
    os.umask(0022)

    try:
        main()
    except KeyboardInterrupt:
        print 'Aborted'
