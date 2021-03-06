import os
import shutil

from setuptools import setup, Command, find_packages

VERSION = '0.1.0.dev4'


class UninstallCommand(Command):
    description = "information on how to uninstall utools"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        try:
            import utools

            print('To uninstall, manually remove the Python package folder located here: {0}'.format(
                os.path.split(utools.__file__)[0]))
        except ImportError:
            raise (ImportError("Either utools is not installed or not available on the Python path."))


binary_files = []
test_binary_dir = os.path.join('src', 'utools', 'test', 'bin')
for root, dirs, files in os.walk(test_binary_dir):
    for f in files:
        to_append = os.path.join(root, f)
        to_append = to_append.replace(test_binary_dir, 'bin')
        binary_files.append(to_append)
package_data = {'ocgis.test': binary_files}

temporary_scripts_dir = os.path.join('src', '_scripts')
temporary_scripts_target = os.path.join('src', '_scripts', 'utools_cli')
if not os.path.exists(temporary_scripts_dir):
    os.makedirs(temporary_scripts_dir)
    remove_scripts_dir = True
else:
    remove_scripts_dir = False
shutil.copyfile(os.path.join('src', 'utools_cli.py'), temporary_scripts_target)

setup(
    name='utools',
    version=VERSION,
    author='NESII/CIRES/NOAA-ESRL',
    author_email='ben.koziol@noaa.gov',
    url='https://github.com/NESII/ugrid-tools',
    license='NCSA License',
    platforms=['all'],
    packages=find_packages(where='./src'),
    package_dir={'': 'src'},
    package_data=package_data,
    cmdclass={'uninstall': UninstallCommand},
    install_requires=['mpi4py', 'ESMPy', 'netCDF4', 'shapely', 'fiona', 'click'],
    tests_require=['nose'],
    scripts=[temporary_scripts_target],
)

if remove_scripts_dir:
    shutil.rmtree(temporary_scripts_dir)
