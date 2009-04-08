CREATE TABLE repos (reponame TEXT, PRIMARY KEY (reponame));
CREATE TABLE packages (packagename TEXT, PRIMARY KEY (packagename));
CREATE TABLE versioned_packages (
	reponame TEXT, packagename TEXT, version TEXT, release REAL,
	PRIMARY KEY (reponame, packagename));

CREATE TABLE files (
	reponame TEXT, packagename TEXT, version TEXT,
	release REAL, filename TEXT,
	FOREIGN KEY (packagename) REFERENCES packages,
	FOREIGN KEY (reponame) REFERENCES repos,
	PRIMARY KEY (reponame, packagename, filename));

/*  FOREIGN KEY is here for purposes of documentation, sqlite ignores it. */
