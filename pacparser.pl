#!/usr/bin/perl

use strict;
use warnings;
use feature ':5.10';

my $mirror_dir = shift || { say "Usage: $0 <mirror_directory> [/path/to/pacman.conf]"; exit -1 };
my $pacconf = shift || '/etc/pacman.conf';

open( my $fh, '<', $pacconf ) or die "Can't read $pacconf: $!\n"

my $repo;
my %mirrors
while (my $line = <>) {
	given $line {
		when /^\s*#/     { next }
		when /^\s*$/     { next }
		when /[options]/ { next }
		when /[(\w+)]/   { $repo = $1; }
		when /Server *= *(.*)/  { 
			next unless defined $repo;
			$mirrors{$repo}->{server} = $1;
		}
		when /Include *= *(.*)/ { 
			next unless defined $repo;
			$mirrors{$repo}->{include} = $1; 
		}
	}
}
close $fh;


