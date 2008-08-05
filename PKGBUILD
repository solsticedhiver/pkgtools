# Contributor: Daenyth <Daenyth+Arch AT gmail DOT com>
pkgname=pkgtools
pkgver=8
pkgrel=1
pkgdesc="A collection of scripts for Arch Linux packages"
arch=(any)
url="http://bbs.archlinux.org/viewtopic.php?pid=384196"
license=('GPL')
source=(newpkg pkgfile aurball spec2arch
        functions
        newpkg.conf pkgfile.conf spec2arch.conf
	spec2arch.8 spec2arch.conf.5
        pkgfile-hook pkgfile.cron)
backup=('etc/pkgtools/newpkg.conf' 'etc/pkgtools/pkgfile.conf' 'etc/pkgtools/spec2arch.conf')
replaces=(newpkg)
conflicts=(newpkg)
provides=(newpkg)
install="$pkgname.install"
optdepends=('zsh: For command not found hook'
            'cron: For pkgfile --update entry')


build() {
  # Common fucntions needed by all scripts
  install -Dm644 "${srcdir}/functions"        "${pkgdir}/usr/share/pkgtools/functions"

  # newpkg
  install -Dm755 "${srcdir}/newpkg"           "${pkgdir}/usr/bin/newpkg"
  install -Dm644 "${srcdir}/newpkg.conf"      "${pkgdir}/etc/pkgtools/newpkg.conf"

  # pkgfile
  install -d "$pkgdir/usr/share/pkgtools/lists/"
  install -Dm755 "${srcdir}/pkgfile"          "${pkgdir}/usr/bin/pkgfile"
  install -Dm644 "${srcdir}/pkgfile.conf"     "${pkgdir}/etc/pkgtools/pkgfile.conf"
  install -Dm644 "${srcdir}/pkgfile-hook"     "${pkgdir}/usr/share/pkgtools/pkgfile-hook"
  install -Dm744 "${srcdir}/pkgfile.cron"     "${pkgdir}/etc/cron.daily/pkgfile"

  # aurball
  install -Dm755 "${srcdir}/aurball"          "${pkgdir}/usr/bin/aurball"

  # spec2arch
  install -Dm755 "${srcdir}/spec2arch"        "${pkgdir}/usr/bin/spec2arch"
  install -Dm644 "${srcdir}/spec2arch.conf"   "${pkgdir}/etc/pkgtools/spec2arch.conf"
  install -Dm644 "${srcdir}/spec2arch.8"      "${pkgdir}/usr/share/man/man8/spec2arch.8"
  install -Dm644 "${srcdir}/spec2arch.conf.5" "${pkgdir}/usr/share/man/man8/spec2arch.conf.5"
}

# vim:set ts=2 sw=2 et:
