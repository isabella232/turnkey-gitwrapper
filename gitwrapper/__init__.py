# Copyright (c) 2007 Liraz Siri <liraz@turnkeylinux.org>
# Major refactoring 2019; Jeremy Davis <jeremy@turnkeylinux.org>
#
# This file was part of turnkey-pylib (now defunct).
#
# this software is open source software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.

import sys
import os
from os.path import basename, dirname, exists, isdir, realpath, join, lexists
import subprocess
from subprocess import PIPE, STDOUT
import re


def is_git_repository(path):
    """Return True if path is a git repository"""
    try:
        git = Git(path)
        return True
    except GitError:
        return False


def setup(method):
    """Decorator that:
    1) chdirs into git.path
    2) processes arguments (only non-keywords arguments):
       stringifies them (except None, True or False)
       translates all absolute paths inside git.path to be relative to git.path

    """

    def wrapper(self, *args, **kws):
        orig_cwd = os.getcwd()
        os.chdir(self.path)
        os.environ['GIT_DIR'] = self.gitdir

        def make_relative(arg):
            for constant in (None, True, False):
                if arg is constant:
                    return arg

            if isinstance(arg, (list, tuple)):
                return list(map(make_relative, arg))

            try:
                return self.make_relative(arg)
            except self.GitError:
                return arg

        args = list(map(make_relative, args))

        try:
            ret = method(self, *args, **kws)
        finally:
            os.chdir(orig_cwd)

        return ret

    return wrapper


class GitError(Exception):
    pass


class Git(object):
    """Class for interfacing with a git repository.

    Most methods that are documented to return values raise an exception on
    error, except if the method is documented to return None on error.
    """
    GitError = GitError

    class MergeMsg(object):
        """Magical attribute.

        Set writes to .git/MERGE_MSG
        Get reads value from .git/MERGE_MSG
        """

        def get_path(self, obj):
            return join(obj.path, ".git", "MERGE_MSG")

        def __get__(self, obj, type):
            path = self.get_path(obj)
            if exists(path):
                return file(path, "r").read()

            return None

        def __set__(self, obj, val):
            path = self.get_path(obj)
            file(path, "w").write(val)

    MERGE_MSG = MergeMsg()

    class IndexLock(object):
        def get_path(self, obj):
            return join(obj.gitdir, "index.lock")

        def __get__(self, obj, type):
            path = self.get_path(obj)
            return exists(path)

        def __set__(self, obj, val):
            path = self.get_path(obj)
            if val:
                file(path, "w").close()
            else:
                if exists(path):
                    os.remove(path)

    index_lock = IndexLock()

    @classmethod
    def init_create(cls, path, bare=False, verbose=False):
        if not lexists(path):
            os.mkdir(path)

        init_path = path
        if not bare:
            init_path = join(init_path, ".git")

        command = subprocess.run(
                ['git', '--git-dir', init_path, 'init'],
                stdout=PIPE, stderr=STDOUT)
        if command.returncode != 0:
            raise GitError(command.stdout.decode('utf-8'))
        elif verbose:
            print(command.stdout.decode('utf-8'))

        return cls(path)

    def __init__(self, path):
        # heuristic: if the path has a .git directory in it, then its not bare
        # otherwise we assume its a bare repo if
        # 1) it ends with .git
        # 2) seems to be initialized (objects and refs directories exist)
        self.path = realpath(path)
        path_git = join(self.path, ".git")
        if isdir(path_git):
            self.bare = False
            self.gitdir = path_git
        elif (self.path.endswith(".git") and
              isdir(join(self.path, "refs")) and
              isdir(join(self.path, "objects"))):
            self.bare = True
            self.gitdir = self.path
        else:
            raise self.GitError("Not a git repository `%s'" % self.path)

    def make_relative(self, path):
        path = str(path)
        path = join(realpath(dirname(path)), basename(path))

        if not (path == self.path or path.startswith(self.path + "/")):
            raise self.GitError("path not in the git repository (%s)" % path)

        return path[len(self.path):].lstrip("/")

    @setup
    def _system(self, command, *args, check_returncode=True):
        # command should be a list already, but just in case...
        command = ['git'] + list(command) + list(args)
        output = subprocess.run(command, stderr=PIPE)
        if check_returncode:
            if output.returncode != 0:
                raise self.GitError(output.stderr.decode('utf-8'))
        else:
            return output.returncode

    def read_tree(self, *opts):
        """git read-tree *opts"""
        self._system("read-tree", *opts)

    def update_index(self, *paths):
        """git update-index --remove <paths>"""
        self._system("update-index", "--remove", *paths)

    def update_index_refresh(self):
        """git update-index --refresh"""
        self._system("update-index", "-q", "--unmerged", "--refresh")

    @setup
    def update_index_all(self):
        """update all files that need update according to git update-index
        --refresh"""
        command = subprocess.run(
                ['git', 'update-index', '--refresh'],
                stdout=PIPE,
                stderr=STDOUT)
        if command.returncode == 0:
            return
        output = command.stdout.decode('utf-8')
        files = [line.rsplit(':', 1)[0] for line in output.split('\n')
                 if line.endswith("needs update")]
        self.update_index(*files)

    def add(self, *paths):
        """git add <path>"""
        # git add chokes on empty directories
        self._system("add", *paths)

    def checkout(self, *args):
        """git checkout *args"""
        self._system("checkout", *args)

    def checkout_index(self):
        """git checkout-index -a -f"""
        self._system("checkout-index", "-a", "-f")

    def update_ref(self, *args):
        """git update-ref [ -d ] <ref> <rev> [ <oldvalue > ]"""
        self._system("update-ref", *args)

    def rm_cached(self, path):
        """git rm <path>"""
        self._system("rm", "--ignore-unmatch", "--cached",
                     "--quiet", "-f", "-r", path)

    def commit(self, paths=(), msg=None, update_all=False, verbose=False):
        """git commit"""
        command = ["commit"]
        if update_all:
            command.append("-a")
        if verbose:
            command.append("-v")

        if msg:
            self._system(command, "-m", msg, *paths)
        else:
            self._system(command, *paths)

    def merge(self, remote):
        """git merge <remote>"""
        self._system("merge", remote)

    def reset(self, *args):
        """git reset"""
        self._system("reset", *args)

    def branch_delete(self, branch):
        """git branch -D <branch>"""
        self._system("branch", "-D", branch)

    def branch(self, *args):
        """git branch *args"""
        self._system("branch", *args)

    def prune(self):
        """git prune"""
        self._system("prune")

    def repack(self, *args):
        """git repack *args"""
        self._system("repack", *args)

    def fetch(self, repository, refspec):
        self._system("fetch", repository, refspec)

    def raw(self, command, *args):
        """execute a raw git command.
        Returns:
            exit status code if command failed
            None if it was successfuly"""

        exitcode = self._system(command, *args, check_returncode=False)
        if exitcode == 0:
            return None
        else:
            return exitcode

    @setup
    def _getoutput(self, command, *args, check_returncode=True, stderr=STDOUT):
        output = subprocess.run(
                ['git', command] + list(args),
                stdout=PIPE,
                stderr=stderr)
        if check_returncode and output.returncode != 0:
            raise self.GitError(output.stdout.decode('utf-8'))

        return output.stdout.decode('utf-8')

    def cat_file(self, *args):
        return self._getoutput("cat-file", *args)

    def write_tree(self):
        """git write-tree
        Returns id of written tree"""
        return self._getoutput("write-tree")

    def rev_parse(self, *args):
        """git rev-parse <rev>.
        Returns object-id of parsed rev.
        Returns None on failure.
        """
        try:
            return self._getoutput("rev-parse", *args)
        except self.GitError:
            return None

    def merge_base(self, a, b):
        """git merge-base <a> <b>.
        Returns common ancestor"""
        try:
            return self._getoutput("merge-base", a, b)
        except self.GitError:
            return None

    def symbolic_ref(self, name, ref=None):
        """git symbolic-ref <name> [ <ref> ]
        Returns the value of the symbolic ref.
        """
        args = ["symbolic-ref", name]
        if ref:
            args.append(ref)
        return self._getoutput(*args)

    def rev_list(self, *args, check_returncode=True):
        """git rev-list <commit>.
        Returns list of commits.
        """
        output = self._getoutput("rev-list", *args, check_returncode=check_returncode)
        if not output:
            return []
        # remove empty lines from list
        return list(filter(None, output.split('\n')))

    def name_rev(self, rev):
        """git name-rev <rev>
        Returns name of rev"""
        return self._getoutput("name-rev", rev).split(" ")[1]

    def show_ref(self, ref):
        """git show-ref <rev>.
        Returns ref name if succesful
        Returns None on failure"""
        try:
            return self._getoutput("show-ref", ref).split(" ")[1]
        except self.GitError:
            return None

    def show(self, *args):
        """git show *args -> output"""
        return self._getoutput("show", *args)

    @setup
    def describe(self, *args):
        """git describe *args -> list of described tags.

        Note: git describe terminates on the first argument it can't
        describe and we ignore that error.
        """
        return self._getoutput(
                "describe", *args,
                check_returncode=False, stderr=PIPE
                ).splitlines()

    @setup
    def commit_tree(self, id, log, parents=None):
        """git commit-tree <id> [ -p <parents> ] < <log>
        Return id of object committed"""
        args = ["git", "commit-tree", id]
        if parents:
            if not isinstance(parents, (list, tuple)):
                parents = [parents]

            for parent in parents:
                args += ["-p", parent]

        p = subprocess.Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        try:
            p.stdin.write(log)
            p.stdin.close()
        except IOError:
            pass

        err = p.wait()
        if err:
            raise self.GitError("git commit-tree failed: " + p.stderr.read())

        return p.stdout.read().strip()

    def mktree_empty(self):
        """return an empty tree id which is needed for some comparisons"""

        args = ["git", "mktree"]
        p = subprocess.Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        try:
            p.stdin.close()
        except IOError:
            pass

        err = p.wait()
        if err:
            raise self.GitError("git mktree failed: " + p.stderr.read())

        return p.stdout.read().strip()

    @setup
    def log(self, *args, oneline=False, count=0):
        """git log *args
        Return stdout pipe"""
        command = ['log']
        if oneline:
            command.append('--oneline')
        if count != 0:
            command.append('-{}'.format(count))
        command = command + list(args)

        return self._getoutput(*command, stderr=PIPE)

    def get_latest_tag(self) -> str:
        """git describe --tags $(git rev-list --tags --max-count=1)
        Returns latest tag. If no tags found, returns False."""
        # don't check_returncode as it will exit non-zero if no tags
        latest_tagged_commit = self.rev_list(
                    '--tags', '--max-count=1', check_returncode=False)
        if len(latest_tagged_commit) != 1:
            # should return one result, otherwise there are no tags
            return False
        return self.describe('--tags', latest_tagged_commit[0])[0]

    def get_latest_commit(self, short=True) -> str:
        """git rev-parse [--short] HEAD
        Returns latest commit short ID by default, long ID if short=False."""
        args = []
        if short:
            args.append('--short')
        args.append('HEAD')
        return self.rev_parse(*args).strip()

    def status(self, *paths):
        """git diff-index --name-status HEAD
        Returns array of (status, path) changes """

        self.update_index_refresh()
        output = self._getoutput("diff-index", "--ignore-submodules",
                                 "--name-status", "HEAD", *paths)
        if output:
            return [line.split('\t', 1) for line in output.split('\n')]
        return []

    def status_full(self, simple=True):
        """git status
        While simple=True; returns True if clean; False if any uncommitted,
        unstaged, or untracked files.
        While simple=False; returns a dictionary of categories, containing
        lists of files."""

        items = list(filter(
            None, self._getoutput('status', '--porcelain').split('\n')))
        if simple:
            if len(items) == 0:
                return True
            return False

        stati = (('uncommited', 'M  '), ('unstaged', ' M '),
                 ('untracked', '?? '))

        def _check_status(item):
            for status, prefix in stati:
                if item.startswith(prefix):
                    return status, item[len(prefix):]
            raise GitError(
                    'Unrecongnized git status prefix in "{}"'.format(item))

        files_sorted = {'uncomitted': [], 'unstaged': [], 'untracked': []}
        for item in items:
            status, filename = _check_status(item)
            files_sorted[status].append(filename)
        return files_sorted

    def list_unmerged(self):
        output = self._getoutput("diff", "--name-only", "--diff-filter=U")
        if output:
            return output.split('\n')
        return []

    def get_commit_log(self, committish):
        """Returns commit log text for <committish>"""

        str = self._getoutput("cat-file commit", committish)
        return str[str.index('\n\n') + 2:]

    def ls_files(self, *args):
        return self._getoutput("ls-files", *args).splitlines()

    def list_changed_files(self, compared, *paths):
        """Return a list of files that changed between compared.

        If compared is tuple/list with 2 elements, we compare the
        compared[0] and compared[1] with git diff-tree.

        If compared is not a tuple/list, or a tuple/list with 1 element,
        we compare compared with git diff-index which compares a commit/treeish
        to the index."""

        self.update_index_refresh()
        if not isinstance(compared, (list, tuple)):
            compared = [compared]

        if len(compared) == 2:
            str = self._getoutput("diff-tree", "-r", "--name-only",
                                  compared[0], compared[1], *paths)
        elif len(compared) == 1:
            str = self._getoutput("diff-index", "--ignore-submodules", "-r",
                                  "--name-only", compared[0], *paths)
        else:
            raise self.GitError("compared does not contain 1 or 2 elements")

        if str:
            return str.split('\n')
        return []

    def list_refs(self, refpath):
        try:
            output = self._getoutput("show-ref", "--", refpath)
        except self.GitError as e:
            if e == '':
                return []
            raise

        tags = []
        regexp = re.compile('^[0-9a-f]+ refs/%s/(.*)' % refpath)
        for line in output.splitlines():
            m = regexp.match(line)
            if not m:
                continue
            tag = m.group(1)
            tags.append(tag)

        return tags

    def list_heads(self):
        return self.list_refs("heads")

    def list_tags(self):
        return self._getoutput("tag").split()

    def remove_ref(self, ref):
        """deletes refs/<ref> from the git repository"""
        self.update_ref("-d", join("refs", ref))

    def remove_tag(self, name):
        self.remove_ref("tags/" + name)

    def set_alternates(self, git):
        """set alternates path to point to the objects path of the specified
        git object"""

        fh = file(join(self.gitdir, "objects/info/alternates"), "w")
        print(join(git.gitdir, "objects"), file=fh)
        fh.close()

    def stash(self):
        msg = self.__getoutput("stash")
        if msg.startswith('No local changes to save'):
            return False
        return msg

    def stash_pop(self):
        try:
            msg = self.__getoutput("stash", "pop")
        except GitError as e:
            if e.startswith('No stash found'):
                return False
            raise
        return msg

    def remote(self, *args, list_all=False):
        if list_all:
            result = self.__getoutput("remote", "-v")
            output = {}
            for line in result.split('\n').strip():
                name, location = line.split('\t')
                if name in output.keys():
                    output[name].append(location)
                else:
                    output[name] = [location]
            return output
        else:
            return self.__getoutput("remote", *args)

    @staticmethod
    def set_gitignore(path, lines, append=False):
        if not isinstancei(lines, (list, tuple)):
            lines = lines.split('\n')
        mode = 'w'
        if append:
            mode = 'a'
        with open(join(path, ".gitignore"), mode) as fob:
            for line in lines:
                fob.write(line+'\n')

    @staticmethod
    def anchor(path):
        with open(join(path, ".anchor"), "w") as fob:
            fob.write('')
