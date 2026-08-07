from typing import Optional
import os
import re
import shutil
import subprocess
from download import Downloader
from download import Download
from input import Input
from output import Output
from build import BuildTools, BuildConfiguration


class Project:
    """Represents a project that can be downloaded and optionally built."""

    def __init__(self,
                 name: str,
                 repository: str,
                 branch: str,
                 download_path: str,
                 extract_path: str,
                 env_var_name: str,
                 env_var_value: str,
                 makefile_path: Optional[str],
                 use_codesmithy_make: bool):
        """
        Parameters
        ----------
        name : str
            The name of the project.
        repository : str
            The name of the source repository. Combined with the branch, this
            identifies the source to download.
        branch : str
            The name of the branch to download.
        download_path : str
            The directory where downloaded packages are cached.
        extract_path : str
            The exact directory where the project is unzipped. It is used as-is,
            no path manipulation is done on it.
        env_var_name : str
            The name of the environment variable that will point to the
            location of this project.
        env_var_value : str
            The directory the environment variable points to.
        makefile_path : str, optional
            The exact path of the makefile used to build the project. None if
            the project only needs to be downloaded.
        use_codesmithy_make : bool
            Whether CodeSmithyMake should be used to build the project.
        """

        self.name = name
        self.org = "nuime-build"
        self.repository = repository
        self.branch = branch
        self.download_path = download_path
        self.extract_path = extract_path
        self.env_var_name = env_var_name
        self.env_var_value = env_var_value
        self.makefile_path = makefile_path
        self.use_codesmithy_make = use_codesmithy_make
        self.cmake_generation_args = []

        self.built = False

    def create_downloader(self) -> Downloader:
        """Creates a downloader to download the package(s) for this project.

        Returns
        -------
        Downloader
            An instance of the Downloader class that can be used to download
            the package or packages for this project.
        """

        downloader = Downloader()

        download_url = "https://github.com/" + self.org + "/" + \
                       self.repository + "/archive/" + self.branch + ".zip"

        # The archive is installed at the exact extract_path. Projects that
        # share a repository are given the same extract_path, so their
        # downloads are identical and get deduplicated by Downloader.merge.
        download = Download(self.repository, download_url,
                            self.download_path, self.branch,
                            [self.extract_path])
        downloader.downloads.append(download)

        return downloader

    def unzip(self, downloader: Downloader):
        """Unzips the package(s) for this project.

        In the Project class there is only one package but derived classes can
        specify more than one package to unzip.

        Parameters
        ----------
        downloader : Downloader
            The downloader that was used to download the package(s).
        """

        downloader.unzip(self.repository)

    def build(self, build_tools: BuildTools,
              parent_build_configuration: BuildConfiguration,
              input: Input,
              output: Output):
        """Builds the project.

        Parameters
        ----------
        build_tools : BuildTools
            The build tools. An appropriate build tool will be selected based
            on the type of the project.
        parent_build_configuration : BuildConfiguration
            The parent build configuration. This may be further modified if the
            project has specific settings.
        input : Input
            The input helper.
        output : Output
            The output helper.
        """

        try:
            if self.makefile_path is None:
                print("    No build required for this project")
            else:
                cmake = build_tools.cmake
                compiler = build_tools.compiler
                codesmithymake = build_tools.codesmithymake
                build_configuration = BuildConfiguration(parent_build_configuration)
                build_configuration.cmake_generation_args.extend(self.cmake_generation_args)
                resolved_makefile_path = self._resolve_makefile_path(compiler, build_configuration.architecture_dir_name)
                if not os.path.exists(resolved_makefile_path):
                    raise RuntimeError(resolved_makefile_path + " not found")
                if self.use_codesmithy_make:
                    print("    Using CodeSmithyMake")
                    codesmithymake.build(compiler, resolved_makefile_path,
                                         build_configuration.codesmithymake_configuration,
                                         input)
                elif self.makefile_path.endswith("/CMakeLists.txt"):
                    log = self.name + "_build.log"
                    print("    Using CMake, build log: " + log)
                    cmake.build(resolved_makefile_path, build_configuration,
                                log)
                else:
                    print("    Using " + compiler.name)
                    compiler.compile(resolved_makefile_path,
                                     build_configuration.compiler_configuration,
                                     input)
                print("    Project build successfully")
            self.built = True
        except RuntimeError:
            print("    Failed to build project")
            raise

    def launch(self, compiler, architecture_dir_name):
        compiler.launch(self._resolve_makefile_path(compiler,
                                                    architecture_dir_name))

    def _resolve_makefile_path(self, compiler, architecture_dir_name):
        if compiler.short_name == "GNUmakefile":
            result = re.sub(r"\$\(compiler_short_name\).*",
                            compiler.short_name + "/GNUmakefile",
                            self.makefile_path)
        else:
            result = re.sub(r"\$\(compiler_short_name\)",
                            compiler.short_name,
                            self.makefile_path)
        result = re.sub(r"\$\(arch\)",
                        architecture_dir_name,
                        result)
        return result


class CMakeLibraryProject(Project):
    """A third-party library built with CMake.

    These libraries are built with CMake but CMake doesn't put the library
    where the projects that depend on it expect to find it, so a copy is made
    once the build is done. The headers need no such treatment, the repository
    already has them in the include directory at its root.

    The extracted repository is used as-is: it has a CMakeLists.txt at its root
    and it is where the library is built and installed.
    """

    def __init__(self,
                 name: str,
                 repository: str,
                 branch: str,
                 download_path: str,
                 build_dir: str,
                 env_var_name: str,
                 library_name: str,
                 target):
        """
        Parameters
        ----------
        library_name : str
            The base name of the library as CMake builds it, without the debug
            suffix, the architecture and the extension. For instance the fmt
            library is built as fmt.lib (or fmtd.lib in debug builds) so its
            library name is "fmt".
        target
            The target platform and architecture. The architecture appears in
            the name of the installed library.
        """

        extract_path = build_dir + "/" + name
        super().__init__(name, repository, branch, download_path,
                         extract_path, env_var_name, extract_path,
                         extract_path + "/CMakeLists.txt", False)
        self.library_name = library_name
        self.target = target

    def build(self, build_tools: BuildTools,
              parent_build_configuration: BuildConfiguration,
              input: Input,
              output: Output):
        super().build(build_tools, parent_build_configuration, input, output)
        self._install_library(parent_build_configuration)

    def _install_library(self, build_configuration: BuildConfiguration):
        """Copies the library built by CMake to its expected location.

        The build is done in place so CMake puts the library in a directory
        named after the configuration. The projects that depend on the library
        look for it in the lib directory at the root of the repository and
        under a name that follows the Boost naming convention, so it is copied
        there and renamed. For instance Debug/fmtd.lib becomes lib/fmt-d-x64.lib.

        Parameters
        ----------
        build_configuration : BuildConfiguration
            The build configuration. It selects the directory CMake put the
            library in and whether this is a debug build.
        """

        debug = (build_configuration.cmake_configuration == "Debug")
        # CMake appends a "d" to the name of the library in debug builds, the
        # Boost naming convention uses a "-d" suffix instead.
        source_path = self.extract_path + "/" + \
                      build_configuration.cmake_configuration + "/" + \
                      self.library_name + ("d" if debug else "") + ".lib"
        # The Boost naming convention identifies the architecture with a letter
        # for the architecture family followed by the address model, so a 64-bit
        # x86 build is x64 and a 32-bit one is x32.
        architecture_tag = "x" + self.target.architecture
        destination_dir = self.extract_path + "/lib"
        destination_path = destination_dir + "/" + self.library_name + \
                           ("-d" if debug else "") + "-" + \
                           architecture_tag + ".lib"
        if not os.path.exists(source_path):
            raise RuntimeError(source_path + " not found")
        os.makedirs(destination_dir, exist_ok=True)
        shutil.copyfile(source_path, destination_path)
        print("    Installed " + destination_path)


class libgit2Project(Project):
    def __init__(self, download_path, build_dir, target):
        super().__init__("libgit2", "libgit2_libgit2", "main", download_path,
                         build_dir + "/libgit2", "LIBGIT2",
                         build_dir + "/libgit2",
                         build_dir + "/libgit2/$(arch)/CMakeLists.txt", False)
        self.target = target
        self.cmake_generation_args = ["-DBUILD_SHARED_LIBS=OFF",
                                      "-DSTATIC_CRT=OFF"]

    def create_downloader(self):
        # On Windows libgit2 is built separately for each architecture, so the
        # same download is installed into both a Win32 and an x64 directory.
        if self.target.platform == "Linux":
            return super().create_downloader()
        download_url = "https://github.com/" + self.org + "/" + \
                       self.repository + "/archive/" + self.branch + ".zip"
        downloader = Downloader()
        downloader.downloads.append(
            Download(self.repository, download_url,
                     self.download_path, self.branch,
                     [self.extract_path + "/Win32", self.extract_path + "/x64"]))
        return downloader

class wxWidgetsProject(Project):
    def __init__(self, download_path, build_dir):
        super().__init__("wxWidgets", "wxWidgets", "master", download_path,
                         build_dir + "/wxWidgets", "WXWIN",
                         build_dir + "/wxWidgets",
                         build_dir + "/wxWidgets/build/msw/wx_$(compiler_short_name).sln",
                         False)

    def create_downloader(self):
        downloader = super().create_downloader()
        modules = ["zlib", "libpng", "libexpat", "libjpeg-turbo", "libtiff"]
        url_prefix = "https://github.com/" + self.org + "/"
        url_suffix = "/archive/wx.zip"
        src = self.extract_path + "/src"
        for module in modules:
            downloader.downloads.append(
                Download(module, url_prefix + module + url_suffix,
                         self.download_path, "wx",
                         [src + "/" + module]))
        return downloader

    def unzip(self, downloader):
        super().unzip(downloader)
        src = self.extract_path + "/src"
        downloader.unzip("zlib")
        downloader.unzip("libpng")
        os.rmdir(src + "/png")
        os.rename(src + "/libpng", src + "/png")
        downloader.unzip("libexpat")
        os.rmdir(src + "/expat")
        os.rename(src + "/libexpat", src + "/expat")
        downloader.unzip("libjpeg-turbo")
        os.rmdir(src + "/jpeg")
        os.rename(src + "/libjpeg-turbo", src + "/jpeg")
        downloader.unzip("libtiff")
        os.rmdir(src + "/tiff")
        os.rename(src + "/libtiff", src + "/tiff")

    def _resolve_makefile_path(self, compiler, architecture_dir_name):
        return re.sub(r"\$\(compiler_short_name\)",
                      compiler.short_name.lower(),
                      self.makefile_path)


class Test:
    def __init__(self, project_name, executable):
        self.project_name = project_name
        self.executable = executable


class Projects:
    def __init__(self, target, config):
        self.config = config
        self.downloader = Downloader()
        self.projects = []
        # fmt is a dependency of all the other projects so it is built first.
        self.projects.append(CMakeLibraryProject(
            "fmt", "ishiko-cpp_fmt", "master", config.downloads_dir,
            config.build_dir, "FMT_ROOT", "fmt", target))
        self.projects.append(Project(
            "pugixml",
            "ishiko-cpp_pugixml",
            "master",
            config.downloads_dir,
            config.build_dir + "/pugixml",
            "PUGIXML_ROOT",
            config.build_dir + "/pugixml",
            None,
            False))
        self.projects.append(CMakeLibraryProject(
            "yaml-cpp", "ishiko-cpp_yaml-cpp", "master", config.downloads_dir,
            config.build_dir, "YAML_CPP_ROOT", "yaml-cpp", target))
        self.projects.append(libgit2Project(config.downloads_dir, config.build_dir, target))
        self._add_ishiko_project(
            "Ishiko/BasePlatform",
            "ishiko-cpp_base-platform",
            "build-files/$(compiler_short_name)/IshikoBasePlatform.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Errors",
            "ishiko-cpp_errors",
            "build-files/$(compiler_short_name)/IshikoErrors.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Memory",
            "ishiko-cpp_memory",
            "build-files/$(compiler_short_name)/IshikoMemory.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Types",
            "ishiko-cpp_types",
            "build-files/$(compiler_short_name)/IshikoTypes.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Collections",
            "ishiko-cpp_collections",
            "build-files/$(compiler_short_name)/IshikoCollections.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Text",
            "ishiko-cpp_text",
            "build-files/$(compiler_short_name)/IshikoText.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Time",
            "ishiko-cpp_time",
            "build-files/$(compiler_short_name)/IshikoTime.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Process",
            "ishiko-cpp_process",
            "build-files/$(compiler_short_name)/IshikoProcess.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/IO",
            "ishiko-cpp_io",
            "build-files/$(compiler_short_name)/IshikoIO.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/FileSystem",
            "ishiko-cpp_filesystem",
            "build-files/$(compiler_short_name)/IshikoFileSystem.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Configuration",
            "ishiko-cpp_configuration",
            "build-files/$(compiler_short_name)/IshikoConfiguration.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Color",
            "ishiko-cpp_color",
            "build-files/$(compiler_short_name)/IshikoColor.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Terminal",
            "ishiko-cpp_terminal",
            "build-files/$(compiler_short_name)/IshikoTerminal.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/Workflows",
            "ishiko-cpp_workflows",
            "build-files/$(compiler_short_name)/IshikoWorkflows.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/UUIDs",
            "ishiko-cpp_uuids",
            "build-files/$(compiler_short_name)/IshikoUUIDs.sln",
            False)
        self._add_diplodocusdb_project(
            "DiplodocusDB/Core",
            "diplodocusdb_core",
            "build-files/$(compiler_short_name)/DiplodocusDBCore.sln",
            False)
        self._add_diplodocusdb_project(
            "DiplodocusDB/PhysicalStorage",
            "diplodocusdb_physical-storage",
            "build-files/$(compiler_short_name)/DiplodocusDBPhysicalStorage.sln",
            False)
        self._add_diplodocusdb_project(
            "DiplodocusDB/EmbeddedDocumentDB/StorageEngine",
            "diplodocusdb_embedded-document-db",
            "storage-engine/build-files/$(compiler_short_name)/"
            "DiplodocusEmbeddedDocumentDBStorageEngine.sln",
            False)
        self._add_diplodocusdb_project(
            "DiplodocusDB/EmbeddedDocumentDB/Database",
            "diplodocusdb_embedded-document-db",
            "database/build-files/$(compiler_short_name)/"
            "DiplodocusEmbeddedDocumentDB.sln",
            False)
        self._add_codesmithyide_project(
            "Nuime/BuildToolchains",
            "build-toolchains",
            "build-files/$(compiler_short_name)/nuime_buildtoolchains.sln",
            False)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/BuildFiles",
            "build-files",
            "build-files/$(compiler_short_name)/CodeSmithyBuildFiles.sln",
            False)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/VersionControl/Git",
            "version-control",
            "git/build-files/$(compiler_short_name)/CodeSmithyGit.sln",
            False)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/Nuime/Library",
            "nuime",
            "library/build-files/$(compiler_short_name)/nuime_lib.sln",
            False)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/Nuime/CLI",
            "nuime",
            "cli/build-files/$(compiler_short_name)/nuime_cli.sln",
            False)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/Core",
            "codesmithy",
            "core/build-files/$(compiler_short_name)/CodeSmithyCore.sln",
            False)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/CLI",
            "codesmithy",
            "cli/build-files/$(compiler_short_name)/CodeSmithyCLI.sln",
            False)
        self._add_ishiko_project(
            "Ishiko/TestFramework/Core",
            "ishiko-cpp_test-framework",
            "core/build-files/$(compiler_short_name)/IshikoTestFrameworkCore.sln",
            True)
        self._add_ishiko_project(
            "Ishiko/WindowsRegistry",
            "ishiko-cpp_windows-registry",
            "Makefiles/$(compiler_short_name)/IshikoWindowsRegistry.sln",
            True)
        self._add_ishiko_project(
            "Ishiko/FileTypes",
            "ishiko-cpp_file-types",
            "Makefiles/$(compiler_short_name)/IshikoFileTypes.sln",
            True)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/UICore",
            "codesmithy",
            "UICore/Makefiles/$(compiler_short_name)/CodeSmithyUICore.sln",
            True)
        self.projects.append(wxWidgetsProject(config.downloads_dir, config.build_dir))
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/UIElements",
            "codesmithy",
            "UIElements/Makefiles/$(compiler_short_name)/CodeSmithyUIElements.sln",
            True)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/UIImplementation",
            "codesmithy",
            "UIImplementation/Makefiles/$(compiler_short_name)/"
            "CodeSmithyUIImplementation.sln",
            True)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/UI",
            "codesmithy",
            "UI/Makefiles/$(compiler_short_name)/CodeSmithy.sln",
            True)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/Tests/Core",
            "codesmithy",
            "core/tests/build-files/$(compiler_short_name)/"
            "CodeSmithyCoreTests.sln",
            True)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/Tests/Make",
            "codesmithy",
            "Tests/Make/Makefiles/$(compiler_short_name)/"
            "CodeSmithyMakeTests.sln",
            True)
        self._add_codesmithyide_project(
            "CodeSmithyIDE/CodeSmithy/Tests/UICore",
            "codesmithy",
            "Tests/UICore/Makefiles/$(compiler_short_name)/"
            "CodeSmithyUICoreTests.sln",
            True)
        self.tests = []
        self.tests.append(Test("CodeSmithyIDE/CodeSmithy/Tests/Core",
                               "CodeSmithyCoreTests.exe"))
        self._init_downloader()

    def get(self, name):
        for project in self.projects:
            if project.name == name:
                return project
        return None

    def set_environment_variables(self, output):
        print("")
        output.print_step_title("Setting environment variables")
        env = {}
        for project in self.projects:
            value = os.getcwd() + "/" + project.env_var_value
            if project.env_var_name in env:
                old_value = env[project.env_var_name]
                if (old_value != value):
                    exception_text = "Conflicting values for " + \
                        "environment variable " + project.env_var_name + " (" + \
                        value + " vs " + old_value + ")"
                    raise RuntimeError(exception_text)
            else:
                env[project.env_var_name] = value
        for var_name in env:
            print("    " + var_name + ": " + env[var_name])
            os.environ[var_name] = env[var_name]
        output.next_step()

    def download(self):
        self.downloader.download()

    def build(self, build_tools, build_configuration,
              input, state, output):
        # For now only bypass pugixml, libgit2 and wxWidgets because they
        # are independent from the rest. More complex logic is required to
        # handle the other projects.
        # Unless we have built all project succesfully.
        for project in self.projects:
            if state.build_complete:
                project.built = True
            elif project.name in ["libgit2", "pugixml", "wxWidgets"]:
                if project.name in state.built_projects:
                    project.built = True
        for project in self.projects:
            print("")
            output.print_step_title("Building " + project.name)
            if project.built:
                print("    Using previous execution")
            else:
                project.unzip(self.downloader)
                project.build(build_tools, build_configuration,
                              input, output)
            state.set_built_project(project.name)
            output.next_step()
        state.set_build_complete()

    def test(self, compiler, architecture_dir_name, input):
        for test in self.tests:
            # TODO
            executable_path = self.config.build_dir + "/" + test.project_name + \
                              "/Makefiles/vc15/x64/Debug/" + test.executable
            try:
                subprocess.check_call([executable_path])
            except subprocess.CalledProcessError:
                launchIDE = input.query("    Tests failed. Do you you want to"
                                        " launch the IDE?", ["y", "n"], "n")
                if launchIDE == "y":
                    self.get(test.project_name).launch(compiler,
                                                       architecture_dir_name)
                raise RuntimeError(test.project_name + " tests failed.")

    def _add_ishiko_project(self,
                            name: str,
                            repository: str,
                            makefile_path: Optional[str],
                            use_codesmithy_make: bool):
        """Adds a project from the ishiko-cpp namespace.

        The install location is derived from the repository name: the '_'
        separates the namespace from the repository name, so
        ishiko-cpp_base-platform is the base-platform repository of the
        ishiko-cpp namespace and is unzipped at
        <build_dir>/ishiko/cpp/base-platform.

        This layout is the one the projects expect: they refer to their
        dependencies as $(ISHIKO_CPP_ROOT)/<repository name>, so
        ISHIKO_CPP_ROOT points at the namespace directory and each repository
        sits directly below it under its own name.

        Parameters
        ----------
        makefile_path : str, optional
            The path of the makefile relative to the root of the extracted
            repository. None if the project only needs to be downloaded.

        Raises
        ------
        RuntimeError
            If the repository is not a repository of the ishiko-cpp namespace.
        """

        namespace, separator, repository_name = repository.partition("_")
        if (separator != "_") or (namespace != "ishiko-cpp"):
            exception_text = repository + " is not a repository of the " + \
                             "ishiko-cpp namespace"
            raise RuntimeError(exception_text)
        namespace_path = self.config.build_dir + "/ishiko/cpp"
        extract_path = namespace_path + "/" + repository_name
        if makefile_path is not None:
            makefile_path = extract_path + "/" + makefile_path
        self.projects.append(Project(name, repository, "main",
                                     self.config.downloads_dir,
                                     extract_path, "ISHIKO_CPP_ROOT",
                                     namespace_path,
                                     makefile_path, use_codesmithy_make))

    def _add_diplodocusdb_project(self,
                                  name: str,
                                  repository: str,
                                  makefile_path: Optional[str],
                                  use_codesmithy_make: bool):
        """Adds a project from the diplodocusdb namespace.

        The install location is derived from the repository name: the '_'
        separates the namespace from the repository name, so diplodocusdb_core
        is the core repository of the diplodocusdb namespace and is unzipped at
        <build_dir>/diplodocusdb/core.

        This layout is the one the projects expect: they refer to their
        dependencies as $(DIPLODOCUSDB_ROOT)/<repository name>, so
        DIPLODOCUSDB_ROOT points at the namespace directory and each repository
        sits directly below it under its own name.

        Parameters
        ----------
        makefile_path : str, optional
            The path of the makefile relative to the root of the extracted
            repository. None if the project only needs to be downloaded.

        Raises
        ------
        RuntimeError
            If the repository is not a repository of the diplodocusdb
            namespace.
        """

        namespace, separator, repository_name = repository.partition("_")
        if (separator != "_") or (namespace != "diplodocusdb"):
            exception_text = repository + " is not a repository of the " + \
                             "diplodocusdb namespace"
            raise RuntimeError(exception_text)
        namespace_path = self.config.build_dir + "/diplodocusdb"
        extract_path = namespace_path + "/" + repository_name
        if makefile_path is not None:
            makefile_path = extract_path + "/" + makefile_path
        self.projects.append(Project(name, repository, "main",
                                     self.config.downloads_dir,
                                     extract_path, "DIPLODOCUSDB_ROOT",
                                     namespace_path,
                                     makefile_path, use_codesmithy_make))

    def _add_codesmithyide_project(self,
                                   name: str,
                                   repository: str,
                                   makefile_path: Optional[str],
                                   use_codesmithy_make: bool):
        """Adds a project from the codesmithyide namespace.

        Unlike the repositories of the other namespaces the ones of the
        codesmithyide namespace are not prefixed with the name of their
        namespace, so there is nothing to strip and the repository name is used
        as-is. The codesmithy repository is unzipped at
        <build_dir>/codesmithyide/codesmithy.

        This layout is the one the projects expect: they refer to their
        dependencies as $(CODESMITHYIDE_ROOT)/<repository name>, so
        CODESMITHYIDE_ROOT points at the namespace directory and each
        repository sits directly below it under its own name.

        Parameters
        ----------
        makefile_path : str, optional
            The path of the makefile relative to the root of the extracted
            repository. None if the project only needs to be downloaded.

        Raises
        ------
        RuntimeError
            If the repository is not a repository of the codesmithyide
            namespace.
        """

        if "_" in repository:
            exception_text = repository + " is not a repository of the " + \
                             "codesmithyide namespace"
            raise RuntimeError(exception_text)
        namespace_path = self.config.build_dir + "/codesmithyide"
        extract_path = namespace_path + "/" + repository
        if makefile_path is not None:
            makefile_path = extract_path + "/" + makefile_path
        self.projects.append(Project(name, repository, "main",
                                     self.config.downloads_dir,
                                     extract_path, "CODESMITHYIDE_ROOT",
                                     namespace_path,
                                     makefile_path, use_codesmithy_make))

    def _init_downloader(self):
        for project in self.projects:
            project_downloader = project.create_downloader()
            self.downloader.merge(project_downloader)
