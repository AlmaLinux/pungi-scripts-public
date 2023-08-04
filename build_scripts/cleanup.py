#!/usr/bin/env python3
# coding=utf-8

import argparse
import logging
import os
from pathlib import Path
from shutil import rmtree

PUNGI_RESULTS = 'pungi-results'

logging.basicConfig(level=logging.INFO)


def create_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--env-path',
        action='store',
        help='A path to folder which will be used '
             'for building new distribution',
        required=True,
    )
    parser.add_argument(
        '--keep-builds',
        action='store',
        help='An amount of kept old builds',
        required=True,
        type=int,
    )
    parser.add_argument(
        '--excluded-dirs',
        help='The list of excluded for deleting dirs',
        required=False,
        nargs='+',
        type=str,
        default=[],
    )
    return parser


def cli_main():

    args = create_parser().parse_args()
    pungi_results_path = os.path.join(
        args.env_path,
        PUNGI_RESULTS,
    )
    dirs_prefixes = [
        'latest-',
        'minimal_iso',
    ]
    dirs_prefixes.extend(
        args.excluded_dirs,
    )
    old_pungi_results = sorted(
        filter(
            lambda i: not any(
                i.name.startswith(dir_prefix) for dir_prefix in dirs_prefixes
            ),
            filter(
                lambda i: i.is_dir(),
                Path(pungi_results_path).iterdir()
            )
        ),
        key=os.path.getmtime,
    )
    if args.keep_builds:
        old_pungi_results = old_pungi_results[:-args.keep_builds]
    for old_pungi_result in old_pungi_results:
        logging.info(
            'Remove old build by path "%s"',
            old_pungi_result,
        )
        rmtree(old_pungi_result)


if __name__ == '__main__':
    cli_main()
