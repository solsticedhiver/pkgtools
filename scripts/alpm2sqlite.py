#!/usr/bin/python

###
# alpm2sqlite.py -- convert an alpm like database to a sqlite one
# This program is a part of pkgtools

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

from sys import argv, stderr, exit
from os import listdir
from os.path import join, exists, isdir, isfile, basename, dirname
from tarfile import open as tfopen, TarError

from cPickle import loads, dumps
from zlib import decompress, compress
import sqlite3
from datetime import datetime

# _getsection and parse_* functions are borrowed from test/pacman/pmdb.py

def _getsection(fd):
    i = []
    while True:
        line = fd.readline().strip("\n")
        if not line:
            break
        i.append(line)
    return i

def parse_files(pkg, f):
    while True:
        line = f.readline()
        if not line:
            break
        line = line.strip("\n")
        if line == "%FILES%":
            pkg['files'] = []
            while line:
                line = f.readline().strip("\n")
                #if line and not line.endswith("/"):
                # also pick the directories
                if line:
                    pkg['files'].append(line)
        if line == "%BACKUP%":
            pkg['backup'] = _getsection(f)

def parse_desc(pkg, f):
    while True:
        line = f.readline()
        if not line:
            break
        line = line.strip("\n")
        if line == "%NAME%":
            pkg['name'] = f.readline().strip("\n")
        if line == "%FILENAME%":
            pkg['filename'] = f.readline().strip("\n")
        elif line == "%VERSION%":
            pkg['version'] = f.readline().strip("\n")
        elif line == "%DESC%":
            pkg['desc'] = f.readline().strip("\n")
        elif line == "%GROUPS%":
            pkg['groups'] = _getsection(f)
        elif line == "%URL%":
            pkg['url'] = f.readline().strip("\n")
        elif line == "%LICENSE%":
            pkg['license'] = _getsection(f)
        elif line == "%ARCH%":
            pkg['arch'] = f.readline().strip("\n")
        elif line == "%BUILDDATE%":
            try:
                pkg['builddate'] = datetime.fromtimestamp(int(f.readline().strip("\n")))
            except ValueError:
                pkg['builddate'] = None
        elif line == "%INSTALLDATE%":
            try:
                pkg['installdate'] = datetime.fromtimestamp(int(f.readline().strip("\n")))
            except ValueError:
                pkg['installdate'] = None
        elif line == "%PACKAGER%":
            pkg['packager'] = f.readline().strip("\n")
        elif line == "%REASON%":
            pkg['reason'] = int(f.readline().strip("\n"))
        elif line == "%SIZE%" or line == "%ISIZE%":
            pkg['isize'] = int(f.readline().strip("\n"))
        elif line == "%CSIZE%":
            pkg['csize'] = int(f.readline().strip("\n"))
        elif line == "%MD5SUM%":
            pkg['md5sum'] = f.readline().strip("\n")
        elif line == "%REPLACES%":
            pkg['replaces'] = _getsection(f)
        elif line == "%FORCE%":
            f.readline()
            pkg['force'] = 1

def parse_depends(pkg, f):
    while True:
        line = f.readline()
        if not line:
            break
        line = line.strip("\n")
        if line == "%DEPENDS%":
            pkg['depends'] = _getsection(f)
        elif line == "%OPTDEPENDS%":
            pkg['optdepends'] = _getsection(f)
        elif line == "%CONFLICTS%":
            pkg['conflicts'] = _getsection(f)
        elif line == "%PROVIDES%":
            pkg['provides'] = _getsection(f)

parse_fctn = {'files':parse_files, 'depends':parse_depends, 'desc':parse_desc}

# pickle and zlib compress lists automatically (for files mainly)
def adapt_list(L):
    # use a buffer to force a BLOB type in sqlite3
    return buffer(compress(dumps(L)))

def convert_list(s):
    return loads(decompress(s))

# Register the adapter
sqlite3.register_adapter(list, adapt_list)

# Register the converter
sqlite3.register_converter("list", convert_list)

# sqlite3 module include already adapter/converter for datetime.datetime
# That's why you'll see datetime in the create statement below

def open_db(dbfile):
    conn = sqlite3.connect(dbfile, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.text_factory = str
    conn.row_factory = sqlite3.Row
    # check the integrity of the db
    try:
        row = conn.execute('pragma integrity_check').fetchone()
    except sqlite3.DatabaseError:
        print >> stderr, 'Error: %s does not seem to be a sqlite3 db.' % dbfile
        exit(2)
    if row[0] != 'ok':
        print >> stderr, 'Error: the db %s is corrupted' % dbfile
        exit(2)

    # do not sync to disk. If the OS crashes, the db will be corrupted.
    conn.execute('pragma synchronous=0')

    # create the db if it's not already there
    conn.execute('''create table if not exists pkg(
        name        varchar(64),
        filename    varchar(64),
        version     varchar(32),
        desc        varchar(512),
        url         varchar(256),
        packager    varchar(128),
        md5sum      varchar(32),
        arch        varchar(6),
        builddate   datetime,
        installdate datetime,
        isize       integer,
        csize       integer,
        reason      integer,
        license     list,
        groups      list,
        depends     list,
        optdepends  list,
        conflicts   list,
        provides    list,
        replaces    list,
        files       list,
        backup      list,
        force       integer)''')

    cur = conn.cursor()

    return (conn, cur)

def commit_pkg(pkg, conn, cur, options):
    row = cur.execute('select rowid from pkg where name=?', (pkg['name'],)).fetchone()
    if row is not None:
        if options.verbose:
            # we could only show the pkgname because convert_tarball pass only
            # incomplete pkg dict
            print ':: Updating %s' % pkg['name']
        cur.execute('update pkg set '+','.join('%s=:%s' % (p,p) for p in pkg)+ ' where name=:name', pkg)
    else:
        if options.verbose:
            # same remark as above
            print ':: Adding %s' % pkg['name']
        cur.execute('insert into pkg ('+','.join(p for p in pkg)+') values('+ ','.join(':%s' % p for p in pkg)+')', pkg)
    conn.commit()

def convert_tarball(tf, conn, cur, options):
    # Do not try to create a complete pkg dict
    # but instead commit to db as soon as we have parsed a file
    for ti in tf:
        if ti.isfile():
            f = tf.extractfile(ti)
            fname = basename(ti.name)
            if fname not in ('desc', 'depends', 'files'):
                continue
            pkgdir = basename(dirname(ti.name))
            pkgname = '-'.join(pkgdir.split('-')[:-2])
            # use pkgver from pkgdir because some repo do not include desc in their
            # *.files.tar.gz (arch-games for example)
            pkgver = '-'.join(pkgdir.split('-')[-2:])
            pkg = {'name':pkgname, 'version':pkgver}
            parse_fctn[fname](pkg, f)
            f.close()

            commit_pkg(pkg, conn, cur, options)

def convert_dir(path, conn, cur, options):
    for pkgdir in sorted(listdir(path)):
        pkgpath = '/'.join((path, pkgdir))
        pkg = {}

        for fname in ('desc', 'depends', 'files'):
            pathfile = join(pkgpath, fname)
            if exists(pathfile):
                with open(pathfile) as f:
                    parse_fctn[fname](pkg, f)

        commit_pkg(pkg, conn, cur, options)

def update_repo_from_dir(path, dbfile, options):
    '''update sqlite db from a repo directory
This function avoids parsing unnecessary files and a lot of I/O'''
    conn, cur = open_db(dbfile)

    # look for new or changed packages
    for pkgdir in sorted(listdir(path)):
        # get name and version from dir name
        pkgname = '-'.join(pkgdir.split('-')[:-2])
        pkgver = '-'.join(pkgdir.split('-')[-2:])

        oldpkg = cur.execute('select version from pkg where name=?', (pkgname,)).fetchone()
        # If not in the db or a different version, include or update it
        update = 0
        if not oldpkg:
            update = 1
        elif oldpkg['version'] != pkgver:
            update = 2
        if update > 0:
            if options.verbose:
                if update == 1:
                    print ':: Adding %s-%s' % (pkgname, pkgver)
                elif update == 2:
                    print ':: Updating %s (%s -> %s)' % (pkgname, oldpkg['version'], pkgver)
            pkgpath = '/'.join((path, pkgdir))
            pkg = {}

            # parse files again
            for fname in ('desc', 'depends', 'files'):
                pathfile = join(pkgpath, fname)
                if exists(pathfile):
                    with open(pathfile) as f:
                        parse_fctn[fname](pkg, f)

            commit_pkg(pkg, conn, cur, options)

    # check for removed package
    rows = cur.execute('select name,version from pkg')
    pkgs = rows.fetchmany()

    while pkgs:
        for pkg in pkgs:
            pkgname, pkgver = pkg
            # look for the directory in the alpm db
            d = join(path, '%s-%s' %( pkgname, pkgver))
            if not isdir(d):
                if options.verbose:
                    print ':: Removing %s-%s' % (pkgname, pkgver)
                cur.execute('delete from pkg where name=?', (pkgname,))
                conn.commit()
        pkgs = rows.fetchmany()

    cur.close()
    conn.close()

def convert(path, dbfile, options):
    '''convert either a repo directory or a *.files.tar.gz to a sqlite3 db'''
    tf = None
    if isfile(path):
        try:
            tf = tfopen(path)
        except TarError:
            print >> stderr, 'Error: Unable to open %s' % path
            return 1

    try:
        conn, cur = open_db(dbfile)
        # clean the db to start from scratch
        cur.execute('delete from pkg')
        conn.commit()
        if tf is not None:
            convert_tarball(tf, conn, cur, options)
        else:
            convert_dir(path, conn, cur, options)

        cur.close()
        conn.close()

        return 0
    except sqlite3.OperationalError, e:
        print >> stderr, 'Error: %s' % e
        return 1

if __name__ == '__main__':
    if len(argv) < 2:
        print '''Usage: %s [directory|somedb.files.tar.gz]
Convert an alpm directory or a .files.tar.gz file to a sqlite db file''' % argv[0]
        exit(1)

    path = argv[1]
    if isdir(path):
        dbfile = basename('%s.db' % path.rstrip('/'))
        print ':: converting %s repo into %s' % (path, dbfile)
    elif isfile(path):
        if path.endswith('.files.tar.gz'):
            dbfile = path.replace('.files.tar.gz', '.db')
        elif path.endswith('.tar.gz'):
            dbfile = path.replace('.tar.gz', '.db')
        elif path.endswith('.tar.bz2'):
            dbfile = path.replace('.tar.bz2', '.db')
        else:
            dbfile = path+'.db' # ??
        print ':: converting %s file into %s' % (path, dbfile)

    exit(convert(path, dbfile))
