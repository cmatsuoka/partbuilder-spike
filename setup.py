#!/usr/bin/env python

from setuptools import setup

setup(
    name="Partbuilder",
    version="0.0",
    description="Just an experiment",
    packages=[
        "partbuilder",
        "partbuilder.cache",
        "partbuilder.cli",
        "partbuilder.cli.partbuilderctl",
        "partbuilder.extractors",
        "partbuilder.grammar",
        "partbuilder.grammar_processing",
        "partbuilder.lifecycle",
        "partbuilder.pluginhandler",
        "partbuilder.plugins",
        "partbuilder.plugins._python",
        "partbuilder.plugins.v1",
        "partbuilder.plugins.v1._python",
        "partbuilder.plugins.v2",
        "partbuilder.repo",
        "partbuilder.sources",
        "partbuilder.states",
        "partbuilder.utils",
    ]
)

