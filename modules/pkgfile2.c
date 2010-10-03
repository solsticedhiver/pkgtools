#include <Python.h>
#define _GNU_SOURCE 1
#include <archive.h>
#include <archive_entry.h>
#include <stdio.h>
#include <stdlib.h>
#include <libgen.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <unistd.h>
#include <fnmatch.h>
#include <regex.h>
#include <pcre.h>
#define ABUFLEN 1024

static cookie_io_functions_t archive_stream_funcs = {
.read = archive_read_data,
.write = NULL,
.seek = NULL,
.close = NULL
};

static FILE *open_archive_stream(struct archive *archive) {
  return fopencookie(archive, "r", archive_stream_funcs);
}

/* from be_files.c in lib/libalpm */
static int splitname(const char *target, char **pkgname, char **pkgver) {
  /* the format of a db entry is as follows:
   *    package-version-rel/
   * package name can contain hyphens, so parse from the back- go back
   * two hyphens and we have split the version from the name.
   */
  char *tmp, *p, *q;

  if(target == NULL) {
    return(-1);
  }
  tmp = strdup(target);
  if(tmp == NULL) {
    return(-1);
  }
  p = tmp + strlen(tmp);

  /* do the magic parsing- find the beginning of the version string
   * by doing two iterations of same loop to lop off two hyphens */
  for(q = --p; *q && *q != '-'; q--);
  for(p = --q; *p && *p != '-'; p--);
  if(*p != '-' || p == tmp) {
    return(-1);
  }

  *pkgver = strdup(p+1);
  /* insert a terminator at the end of the name (on hyphen)- then copy it */
  *p = '\0';
  *pkgname = tmp;

  return 0;
}

static PyObject *list_files(const char *filename,
    int (*match_func)(const char *dbfile, void *data),
    void *data) {
  struct archive *a;
  struct archive_entry *entry;
  struct stat st;
  char pname[ABUFLEN], *fname, *dname, *pkgname, *pkgver;
  char *l = NULL;
  FILE *stream = NULL;
  size_t n = 0;
  int nread;
  PyObject *ret, *pystr;

  pname[ABUFLEN-1]='\0';
  if(stat(filename, &st)==-1 || !S_ISREG(st.st_mode)) {
    PyErr_Format(PyExc_RuntimeError, "File does not exist: %s\n", filename);
    return NULL;
  }

  a = archive_read_new();
  archive_read_support_compression_all(a);
  archive_read_support_format_all(a);
  archive_read_open_filename(a, filename, 10240);
  while (archive_read_next_header(a, &entry) == ARCHIVE_OK) {
    if(!S_ISREG(archive_entry_filetype(entry))) {
      archive_read_data_skip(a);
      continue;
    }
    strncpy(pname, archive_entry_pathname(entry), ABUFLEN-1);
    fname = basename(pname);
    dname = dirname(pname);

    splitname(dname, &pkgname, &pkgver);
    if (pkgname == NULL || pkgver == NULL) {
      archive_read_finish(a);
      return NULL;
    }

    if(!match_func(pkgname, data)) {
      free(pkgname);
      free(pkgver);
      archive_read_data_skip(a);
      continue;
    }
    free(pkgname);
    free(pkgver);

    if(strcmp(fname, "files")) {
      archive_read_data_skip(a);
      continue;
    }

    stream = open_archive_stream(a);
    if (!stream) {
      PyErr_SetString(PyExc_RuntimeError, "Unable to open archive stream.");
      archive_read_finish(a);
      return NULL;
    }

    ret = PyList_New(0);
    if(ret == NULL) {
      archive_read_finish(a);
      return NULL;
    }

    l = NULL;
    while((nread = getline(&l, &n, stream)) != -1) {
      /* Note: getline returns -1 on both EOF and error. */
      /* So I'm assuming that nread > 0. */
      if(l[nread - 1] == '\n')
        l[nread - 1] = '\0';	/* Clobber trailing newline. */
      if(strcmp(l, "%FILES%")) {
        pystr = PyString_FromString(l);
        if(pystr == NULL)
          goto cleanup;
        PyList_Append(ret, pystr);
        Py_DECREF(pystr);
      }
    }
    fclose(stream);
    /* We're done: found our matching package and get all its files */
    break;
  }

  if(l)
    free(l);

  archive_read_finish(a);
  return ret;

cleanup:
  if(l)
    free(l);
  archive_read_finish(a);
  Py_DECREF(ret);
  return NULL;
}

static PyObject *search_file(const char *filename,
    int (*match_func)(const char *dbfile, void *data),
    void *data) {
  struct archive *a;
  struct archive_entry *entry;
  struct stat st;
  char pname[ABUFLEN], *fname, *dname;
  char *l = NULL;
  FILE *stream = NULL;
  size_t n = 0;
  int nread;
  PyObject *ret, *dict, *pystr, *files;

  pname[ABUFLEN-1]='\0';
  if(stat(filename, &st)==-1 || !S_ISREG(st.st_mode)) {
    PyErr_Format(PyExc_RuntimeError, "File does not exist: %s\n", filename);
    return NULL;
  }
  ret = PyList_New(0);
  if(ret == NULL) {
    return NULL;
  }

  files = PyList_New(0);
  if(files == NULL) {
    Py_DECREF(ret);
    return NULL;
  }

  a = archive_read_new();
  archive_read_support_compression_all(a);
  archive_read_support_format_all(a);
  archive_read_open_filename(a, filename, 10240);
  l = NULL;
  while (archive_read_next_header(a, &entry) == ARCHIVE_OK) {
    if(!S_ISREG(archive_entry_filetype(entry))) {
      archive_read_data_skip(a);
      continue;
    }
    strncpy(pname, archive_entry_pathname(entry), ABUFLEN-1);
    fname = basename(pname);
    dname = dirname(pname);
    if(strcmp(fname, "files")) {
      archive_read_data_skip(a);
      continue;
    }

    stream = open_archive_stream(a);
    if (!stream) {
      PyErr_SetString(PyExc_RuntimeError, "Unable to open archive stream.");
      goto cleanup;
    }

    while((nread = getline(&l, &n, stream)) != -1) {
      /* Note: getline returns -1 on both EOF and error. */
      /* So I'm assuming that nread > 0. */
      if(l[nread - 1] == '\n')
        l[nread - 1] = '\0';	/* Clobber trailing newline. */
      if(strcmp(l, "%FILES%") && match_func(l, data)) {
        pystr = PyString_FromString(l);
        if(pystr == NULL)
          goto cleanup;
        PyList_Append(files, pystr);
        Py_DECREF(pystr);
      }
    }

    if(PyList_Size(files) > 0) {
      pystr = PyString_FromString(dname);
      if(pystr == NULL)
        goto cleanup;
      dict = PyDict_New();
      if(dict == NULL) {
        Py_DECREF(pystr);
        goto cleanup;
      }
      PyDict_SetItemString(dict, "package", pystr);
      Py_DECREF(pystr);
      PyDict_SetItemString(dict, "files", files);
      Py_DECREF(files);

      PyList_Append(ret, dict);
      Py_DECREF(dict);

      files = PyList_New(0);
      if(files == NULL)
        goto cleanup_nofiles;
    }
    fclose(stream);
  }

  Py_DECREF(files);
  if(l)
    free(l);

  archive_read_finish(a);
  return ret;

cleanup:
  Py_DECREF(files);
cleanup_nofiles:
  if(l)
    free(l);
  archive_read_finish(a);
  Py_DECREF(ret);
  return NULL;
}

/*
 * Matches the db entry f to the argument m
 * The names must either match completely,
 * or m must match the portion of f after the last /
 */
static int simple_match(const char *f, void *d) {
  char *mb;
  const char *m = (const char*)d;

  if(f==NULL || strlen(f)<=0)
    return 0;
  if((m[0]=='/' && !strcmp(f,m+1)) || !strcmp(f, m))
    return 1;
  mb = rindex(f, '/');
  if(mb != NULL && !strcmp(mb+1,m))
    return 1;
  return 0;
}

static int str_match(const char *f, void *d) {
	return !strcmp(f, (const char *)d);
}

static PyObject *search(PyObject *self, PyObject *args) {
  char *filename, *pattern;

  if(!PyArg_ParseTuple(args, "ss", &filename, &pattern))
    return NULL;
  if(pattern == NULL || strlen(pattern)<=0) {
    PyErr_SetString(PyExc_RuntimeError, "Empty pattern given");
    return NULL;
  }
  return search_file(filename, &simple_match, (void*)pattern);
}

static PyObject *list(PyObject *self, PyObject *args) {
  char *filename, *pattern;

  if(!PyArg_ParseTuple(args, "ss", &filename, &pattern))
    return NULL;
  if(pattern == NULL || strlen(pattern)<=0) {
    PyErr_SetString(PyExc_RuntimeError, "Empty pattern given");
    return NULL;
  }
  return list_files(filename, &str_match, (void*)pattern);
}

static int shell_match(const char *f, void *d) {
  char *mb;
  const char *m = (const char*)d;

  if(f==NULL || strlen(f)<=0)
    return 0;
  mb = rindex(f, '/');
  if(mb != NULL)
    return !fnmatch(m, mb+1, 0);
  return 0;
}

static PyObject *search_shell(PyObject *self, PyObject *args) {
  char *filename, *pattern;

  if(!PyArg_ParseTuple(args, "ss", &filename, &pattern))
    return NULL;
  if(pattern == NULL || strlen(pattern)<=0) {
    PyErr_SetString(PyExc_RuntimeError, "Empty pattern given");
    return NULL;
  }
  return search_file(filename, &shell_match, (void*)pattern);
}

static int regex_match(const char *f, void *d) {
  if(f==NULL || strlen(f)<=0)
    return 0;
  return !regexec((regex_t*)d, f, (size_t)0, NULL, 0);
}

static PyObject *search_regex(PyObject *self, PyObject *args) {
  regex_t re;
  char *filename, *pattern;
  PyObject *ret;

  if(!PyArg_ParseTuple(args, "ss", &filename, &pattern))
    return NULL;
  if(regcomp(&re, pattern, REG_EXTENDED|REG_NOSUB) != 0) {
    PyErr_SetString(PyExc_RuntimeError, "Could not compile regex.");
    return NULL;
  }
  ret = search_file(filename, &regex_match, (void *)&re);
  regfree(&re);
  return ret;
}

struct my_pcredata {
  pcre *re;
  pcre_extra *re_extra;
};

static int pcre_match(const char *f, void *d) {
  if(f==NULL || strlen(f)<=0)
    return 0;
  return pcre_exec(((struct my_pcredata*)d)->re, ((struct my_pcredata*)d)->re_extra, f, strlen(f), 0, 0, NULL, 0) >= 0;
}

static PyObject *search_pcre(PyObject *self, PyObject *args) {
  struct my_pcredata d;
  char *filename, *pattern;
  const char *error;
  int erroffset;
  PyObject *ret;

  if(!PyArg_ParseTuple(args, "ss", &filename, &pattern))
    return NULL;

  d.re = pcre_compile(pattern, 0, &error, &erroffset, NULL);
  if(d.re == NULL) {
    PyErr_Format(PyExc_RuntimeError, "Could not compile regex at %d: %s", erroffset, error);
    return NULL;
  }
  d.re_extra = pcre_study(d.re, 0, &error);
  if(error != NULL) {
    PyErr_Format(PyExc_RuntimeError, "Could not study regex: %s", error);
    pcre_free(d.re);
    return NULL;
  }
  ret = search_file(filename, &pcre_match, (void*)&d);

  pcre_free(d.re);
  pcre_free(d.re_extra);
  return ret;
}

static PyMethodDef PkgfileMethods[] = {
  { "list", (PyCFunction)&list, METH_VARARGS, "List the files of a given package in a file list tarball." },
  { "search", (PyCFunction)&search, METH_VARARGS, "Search for a filename or pathname in a file list tarball." },
  { "search_shell", (PyCFunction)&search_shell, METH_VARARGS, "Search for a filename in a file list tarball using shell pattern matching." },
  { "search_regex", (PyCFunction)&search_regex, METH_VARARGS, "Search for a pathname in a file list tarball using glibc regular expressions." },
  { "search_pcre", (PyCFunction)&search_pcre, METH_VARARGS, "Search for a pathname in a file list tarball using pcre regular expressions." },
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC
initpkgfile(void)
{
  (void) Py_InitModule("pkgfile", PkgfileMethods);
}
