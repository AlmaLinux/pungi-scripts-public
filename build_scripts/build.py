#!/usr/bin/env python3
# coding=utf-8

import argparse
import logging
import os
import subprocess
from pathlib import Path
from shutil import rmtree
from typing import (
    Optional,
    List,
)

PUNGI_RESULTS = 'pungi-results'

logging.basicConfig(level=logging.INFO)


def prepare_koji_env(
        env_path: str,
        local_mirror: str,
        local_repos: List[str],
        koji_excluded_packages: List[str],
):
    koji_env_path = os.path.join(
        env_path,
        'koji',
    )
    logging.info(
        'Update koji env in "%s"',
        koji_env_path,
    )
    if os.path.exists(koji_env_path):
        rmtree(koji_env_path)
    os.makedirs(koji_env_path, exist_ok=True)

    command = (
        f'pungi-gather-rpms -p {local_mirror} -t {koji_env_path} '
        f'-e {" ".join(koji_excluded_packages)}'
    )
    logging.info(command)
    subprocess.check_call(
        command,
        shell=True,
    )
    if local_repos:
        local_repos_paths = ' '.join(
            path for local_repo in local_repos for
            path in map(str, Path(local_mirror).glob(local_repo))
        )
        part_of_command = f'-rd {local_repos_paths}'
    else:
        part_of_command = f'-rp {local_mirror}'
    command = f'pungi-gather-modules {part_of_command} -t {koji_env_path}'
    logging.info(command)
    subprocess.check_call(
        command,
        shell=True,
    )


def run_build(
        env_path: str,
        pungi_label: str,
        result_directory: Optional[str] = None,
):
    logging.info('Run building of distribution')
    pungi_config_name = 'pungi-build.conf'
    command = f'pungi-koji --config {pungi_config_name} --label {pungi_label}'
    if 'Beta-' in pungi_label:
        command += ' --test'
    else:
        command += ' --production'
    if result_directory is not None:
        pungi_results_dir_full_path = os.path.join(
            env_path,
            PUNGI_RESULTS,
        )
        os.makedirs(pungi_results_dir_full_path, exist_ok=True)
        result_dir_full_path = os.path.join(
            pungi_results_dir_full_path,
            result_directory,
        )
        command += f' --compose-dir {result_dir_full_path}'
    else:
        command += f' --target-dir {PUNGI_RESULTS} --no-latest-link'

    logging.info(command)
    subprocess.check_call(
        command,
        shell=True,
        cwd=env_path,
    )


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
        '--local-mirror-path',
        action='store',
        help='A path to local mirror of repos',
        required=True,
    )
    parser.add_argument(
        '--local-repos',
        action='store',
        nargs='*',
        default=[],
        type=str,
        help='List of the local repos in `--local-mirror-path`'
    )
    parser.add_argument(
        '--pungi-label',
        action='store',
        help='A label of an build distribution',
        required=True,
    )
    parser.add_argument(
        '--result-directory',
        action='store',
        help='A path to store the result of building',
        required=False,
        default=None,
    )
    parser.add_argument(
        '--koji-excluded-packages',
        required=False,
        nargs='*',
        type=str,
        default=[],
    )
    return parser


def cli_main():

    args = create_parser().parse_args()
    os.makedirs(
        os.path.join(
            args.env_path,
            PUNGI_RESULTS,
        ),
        exist_ok=True,
    )
    prepare_koji_env(
        env_path=args.env_path,
        local_mirror=args.local_mirror_path,
        local_repos=args.local_repos,
        koji_excluded_packages=args.koji_excluded_packages,
    )
    if args.result_directory is not None and \
            os.path.exists(args.result_directory):
        rmtree(args.result_directory)
    run_build(
        env_path=args.env_path,
        pungi_label=args.pungi_label,
        result_directory=args.result_directory,
    )


if __name__ == '__main__':
    cli_main()
