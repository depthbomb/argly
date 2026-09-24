from os import environ
from setuptools import setup, Extension

extensions = []
if environ.get('ARGLY_CYTHON') == '1':
    from Cython.Build import cythonize

    extensions = cythonize(
        [Extension('argly._parser', ['argly/_parser.py'])],
        build_dir='build/cython',
        compiler_directives={
            'language_level': 3,
            'annotation_typing': False,
            'infer_types': True,
        },
    )

setup(ext_modules=extensions)
