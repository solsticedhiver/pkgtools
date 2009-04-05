CREATE TABLE repos (reponame TEXT, PRIMARY KEY (reponame));
CREATE TABLE packages (packagename TEXT, PRIMARY KEY (packagename));
CREATE TABLE files (
	reponame TEXT, packagename TEXT, version TEXT,
	release INTEGER, filename TEXT,
	FOREIGN KEY (packagename) REFERENCES packages,
	FOREIGN KEY (reponame) REFERENCES repos,
	PRIMARY KEY (reponame, packagename, version, release, filename));

/*  FOREIGN KEY is here for purposes of documentation, sqlite ignores it. */
