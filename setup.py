import os
from distutils.command.build import build

from django.core import management
from setuptools import setup, find_packages


try:
    with open(os.path.join(os.path.dirname(__file__), 'README.rst'), encoding='utf-8') as f:
        long_description = f.read()
except:
    long_description = ''


class CustomBuild(build):
    def run(self):
        management.call_command('compilemessages', verbosity=1, interactive=False)
        build.run(self)


cmdclass = {
    'build': CustomBuild
}


setup(
    name='byro-directdebit',
    version='0.0.2',
    description='This plugin allows membership fees to be collected with SEPA direct debit',
    long_description=long_description,
    url='https://github.com/henryk/byro-directdebit',
    author='Henryk Plötz',
    author_email='henryk@ploetzli.ch',
    license='Apache Software License',

    install_requires=['schwifty', 'workalendar', 'sepaxml==2.2.*'],
    packages=find_packages(exclude=['tests', 'tests.*']),
    include_package_data=True,
    cmdclass=cmdclass,
    entry_points="""
[byro.plugin]
byro_directdebit=byro_directdebit:ByroPluginMeta
""",
)
