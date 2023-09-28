#!/usr/bin/env python3
# coding=utf-8

"""
This script should be inserted to jenkins job
"""
import argparse
import logging
import os
import signal
import subprocess
from distutils.util import strtobool
from pathlib import Path
from typing import (
    List,
    Union,
    Optional,
)

import requests

logging.basicConfig(level=logging.INFO)


def signal_handler(signum, frame, process: subprocess.Popen):
    logging.info(
        'Processing signal "%s" in frame "%s"',
        signal.Signals(signum),
        frame,
    )
    if process.poll() is None:
        process.send_signal(signum)


class Runner:

    def __init__(
            self,
            working_root_directory: Path,
            product_name: str,
            distribution_major_version: int,
            distribution_minor_version: int,
            arch: str,
            branch: str,
            keep_builds: int,
            use_products_repos: bool,
            env_files: List[str],
            beta_suffix: str,
            sigkeys_fingerprints: List[str],
            skip_mirroring: bool,
            local_repos: List[str],
            not_needed_variant: str,
            pgp_sign_keyid: str,
            git_url: str,
            git_project: str,
            git_type: str,
            git_auth_token: str,
            git_auth_username: str,
            sign_service_username: str,
            sign_service_password: str,
            sign_service_endpoint: str,
            koji_excluded_packages: List[str],
    ):
        self.sign_service_username = sign_service_username
        self.sign_service_password = sign_service_password
        self.sign_service_endpoint = sign_service_endpoint
        self.git_url = git_url
        self.git_project = git_project
        self.git_type = git_type
        self.git_auth_username = git_auth_username
        self.git_auth_token = git_auth_token
        self.working_root_directory = working_root_directory
        self.product_name = product_name
        self.distribution_major_version = distribution_major_version
        self.distribution_minor_version = distribution_minor_version
        self.arch = arch
        self.branch = branch
        self.keep_builds = keep_builds
        self.compose_dir = 'last_compose_dir'
        self.use_products_repos = use_products_repos
        self.env_files = env_files
        self.beta_suffix = beta_suffix
        self.sigkeys_fingerprints = sigkeys_fingerprints
        self.skip_mirroring = skip_mirroring
        self.local_repos = local_repos
        self.not_needed_variant = not_needed_variant
        self.pgp_sign_keyid = pgp_sign_keyid
        self.repos_folder = working_root_directory.joinpath(
            f'alma-{distribution_major_version}-{arch}'
        )
        self.koji_excluded_packages = koji_excluded_packages

        self.build_scripts_path = working_root_directory.joinpath(
            'pungi-scripts-public',
            'build_scripts',
        )
        self.env_path = working_root_directory.joinpath(
            f'{self.product_name}{self.distribution_major_version}{self.arch}'
        )
        self.koji_profile_name = (
            f'{self.product_name.lower()}_{self.distribution_major_version}'
        )
        if self.beta_suffix:
            self.pungi_label = (
                f'Beta-{self.distribution_major_version}.'
                f'{self.distribution_minor_version}'
            )
        else:
            self.pungi_label = (
                f'Update-{self.distribution_major_version}.'
                f'{self.distribution_minor_version}'
            )
        self.final_repo_folders = ' '.join(self.get_variants(
            arch=self.arch,
            distribution_major_version=self.distribution_major_version,
            distribution_minor_version=self.distribution_minor_version,
            beta_suffix=self.beta_suffix,
        ))
        self.pungi_configs_git_repo = (
            'https://github.com/AlmaLinux/pungi-scripts-public.git'
        )
        self.compose_dir_full_path = self.env_path.joinpath(
            'pungi-results',
            self.compose_dir,
        )

    @staticmethod
    def run_command(
            command: str,
            exit_or_not: bool = True,
            raise_exception: bool = True,
            use_sudo: bool = True
    ) -> None:

        sudo_suffix = 'sudo' if use_sudo else ''
        cmd_line = f"{sudo_suffix} bash -c \"{command}\""
        logging.info(cmd_line)
        process = subprocess.Popen(
            cmd_line,
            shell=True,
            executable='/bin/bash',
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        for _signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(
                _signum,
                lambda signum, frame: signal_handler(
                    signum=signum,
                    frame=frame,
                    process=process,
                ),
            )

        while process.poll() is None:
            if process.stdout is not None:
                realtime_stdout_line = process.stdout.readline().strip()
                if realtime_stdout_line:
                    print(realtime_stdout_line, flush=True)
        else:
            if process.poll():
                if exit_or_not:
                    exit(process.poll())
                elif raise_exception:
                    raise subprocess.SubprocessError()

    def cleanup(self):
        command = f'cd {self.build_scripts_path} && /usr/bin/env ' \
                  f'python3 cleanup.py ' \
                  f'--env-path {self.env_path} ' \
                  f'--keep-builds {self.keep_builds} '
        if self.compose_dir is not None:
            command = f'{command} --excluded-dirs {self.compose_dir}'
        self.run_command(command=command)

    def enable_products_repos(self):
        suffix = 'products_repos'
        target = Path(f'{self.repos_folder}').joinpath(suffix)
        source = Path(f'{self.repos_folder}-{suffix}')
        if self.use_products_repos:
            logging.info('Enable products repos')
            if not target.is_symlink():
                target.symlink_to(source)
        elif target.exists() and target.is_symlink():
            logging.info('Disable products repos')
            target.unlink(missing_ok=True)

    def prepare(self):

        if not self.skip_mirroring:
            command = (
                f'cd {self.build_scripts_path} && /usr/bin/env '
                f'python3 prepare.py '
                f'--env-path {self.env_path} '
                f'dnf_reposync_synchronize '
                f'{"--use-products-repos " if self.use_products_repos else ""}'
                f'--mirroring-target {self.repos_folder} '
                f'--product-name {self.product_name} '
                f'--arch {self.arch} '
                '--distribution-major-version '
                f'{self.distribution_major_version}'
            )
            self.run_command(command=command)
        self.enable_products_repos()
        command = (
            f'cd {self.build_scripts_path} && /usr/bin/env '
            f'python3 prepare.py '
            f'--env-path {self.env_path} '
            f'add_env_files '
            f'--env-files {" ".join(self.env_files)}'
        )
        self.run_command(command=command)

        command = (
            f'cd {self.build_scripts_path} && /usr/bin/env '
            f'python3 prepare.py '
            f'--env-path {self.env_path} '
            f'add_koji_profile '
            f'--koji-profile-name {self.koji_profile_name}'
        )
        self.run_command(command=command)

        command = (
            f'cd {self.build_scripts_path} && /usr/bin/env '
            f'python3 prepare.py '
            f'--env-path {self.env_path} '
            f'prepare_build_conf '
            f'--product-name {self.product_name} '
            f'--arch {self.arch} '
            f'--distribution-major-version {self.distribution_major_version} '
            f'--distribution-minor-version {self.distribution_minor_version} '
            f'--beta-suffix={self.beta_suffix} '
            f'--sigkeys-fingerprints {" ".join(self.sigkeys_fingerprints)} '
            f'--git-url {self.git_url} '
            f'--git-project {self.git_project} '
            f'--git-type {self.git_type} '
            f'--git-auth-token {self.git_auth_token} '
            f'--git-auth-username {self.git_auth_username}'
        )
        self.run_command(command=command)

    def build(self):
        # remove an old compose dir

        command = (
            f'[[ -d "{self.compose_dir_full_path}" ]] && '
            f'rm -rf {self.compose_dir_full_path}'
        )
        self.run_command(command, exit_or_not=False, raise_exception=False)

        command = (
            f'cd {self.build_scripts_path} && /usr/bin/env '
            f'python3 build.py '
            f'--env-path {self.env_path} '
            f'--local-mirror-path {self.repos_folder} '
            f'--pungi-label {self.pungi_label} '
            f'--result-directory {self.compose_dir} '
            f'--local-repos {" ".join(self.local_repos)} '
            f'--koji-excluded-packages {" ".join(self.koji_excluded_packages)}'
        )
        self.run_command(command=command)

    def post(self):
        command = (
            f'cd {self.build_scripts_path} && /usr/bin/env '
            f'python3 post_actions.py '
            f'--env-path {self.env_path} '
            f'--arch {self.arch} '
            f'--source-repos-folder {self.repos_folder} '
            f'--repos {self.final_repo_folders} '
            f'--not-needed-repos {self.not_needed_variant} '
            f'--pgp-sign-keyid {self.pgp_sign_keyid} '
            f'--sign-service-username {self.sign_service_username} '
            f'--sign-service-password {self.sign_service_password} '
            f'--sign-service-endpoint {self.sign_service_endpoint}'
        )
        self.run_command(command=command)

    @staticmethod
    def get_variants(
            arch: str,
            distribution_major_version: int,
            distribution_minor_version: int,
            beta_suffix: str,
    ) -> List[str]:
        url = (
            'https://git.almalinux.org/almalinux/pungi-almalinux/raw/branch/'
            f'a{distribution_major_version}.{distribution_minor_version}'
            f'{beta_suffix}/{arch}/variants_options.json'
        )
        response = requests.get(url)
        response.raise_for_status()
        variants_data = response.json()  # type: dict
        return list(variants_data.keys())

    def checkout_scripts(self):

        pungi_configs_folder = self.working_root_directory.joinpath(
            'pungi-scripts-public'
        )
        try:
            command = f'ls {pungi_configs_folder}'
            self.run_command(command=command, exit_or_not=False)
            command = (
                f'cd {pungi_configs_folder} && '
                'rm -rf ./* && git checkout -- . && '
                'git fetch && git clean -f && '
                f'git checkout -B {self.branch} origin/{self.branch}'
            )
            self.run_command(command=command)
        except subprocess.SubprocessError:
            command = (
                f'cd {self.working_root_directory} && '
                f'git clone "{self.pungi_configs_git_repo}" '
                f'&& cd {pungi_configs_folder} '
                f'&& git checkout -B {self.branch} origin/{self.branch}'
            )
            self.run_command(command=command)


class StoreAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if values is None or not values:
            raise argparse.ArgumentError(
                self,
                f'Invalid value: {values}',
            )
        setattr(namespace, self.dest, values)


def get_env_var(
        key: str,
        default: Optional[Union[str, int, List]] = None,
        is_bool: bool = False,
        is_multiline: bool = False,
) -> Union[str, bool, int, List[str]]:
    result = os.environ.get(key.lower()) or os.environ.get(key.upper())
    result = result or default
    if is_bool:
        result = strtobool(result)
    if is_multiline:
        result = list(filter(None, result.split('\n')))
    return result


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--working-root-directory',
        action=StoreAction,
        default=get_env_var(key='remote_home_dir'),
        type=Path,
    )
    parser.add_argument(
        '--pgp-sign-keyid',
        action=StoreAction,
        default=get_env_var(key='pgp_sign_keyid'),
        type=str,
    )
    parser.add_argument(
        '--arch',
        action=StoreAction,
        default=get_env_var(key='arch'),
        type=str,
    )
    parser.add_argument(
        '--product-name',
        action=StoreAction,
        default=get_env_var(key='product_name'),
        type=str,
    )
    parser.add_argument(
        '--distribution-major-version',
        action=StoreAction,
        default=get_env_var(key='distribution_major_version'),
        type=int,
    )
    parser.add_argument(
        '--distribution-minor-version',
        action=StoreAction,
        default=get_env_var(key='distribution_minor_version'),
        type=int,
    )
    parser.add_argument(
        '--beta-suffix',
        action='store',
        default=get_env_var(key='beta_suffix', default=''),
        type=str,
    )
    parser.add_argument(
        '--not-needed-variant',
        action=StoreAction,
        default=get_env_var(key='not_needed_variant', default='Minimal'),
        type=str,
    )
    parser.add_argument(
        '--keep-builds',
        action=StoreAction,
        type=int,
        default=get_env_var(key='keep_builds', default=1),
    )
    parser.add_argument(
        '--env-files',
        action='store',
        type=List[str],
        default=get_env_var(
            key='add_env_files',
            default='',
            is_multiline=True,
        ),
        nargs='+',
    )
    parser.add_argument(
        '--local-repos',
        action='store',
        type=List[str],
        default=get_env_var(
            key='local_repos',
            default='',
            is_multiline=True,
        ),
        nargs='+',
    )
    parser.add_argument(
        '--sigkeys-fingerprints',
        action=StoreAction,
        default=get_env_var(
            key='sigkeys_fingerprints',
            default='',
            is_multiline=True,
        ),
        nargs='+',
    )
    parser.add_argument(
        '--skip-mirroring',
        action='store_true',
        default=get_env_var(
            key='skip_mirroring',
            default='False',
            is_bool=True,
        ),
    )
    parser.add_argument(
        '--use-products-repos',
        action='store_true',
        default=get_env_var(
            key='use_products_repos',
            default='False',
            is_bool=True,
        ),
    )
    parser.add_argument(
        '--git-auth-token',
        action='store',
        type=str,
        default=get_env_var(key='git_auth_token'),
    )
    parser.add_argument(
        '--git-auth-username',
        action='store',
        type=str,
        default=get_env_var(key='git_auth_username'),
    )
    parser.add_argument(
        '--git-url',
        action='store',
        type=str,
        default=get_env_var(
            key='git_storage_url',
            default='git.almalinux.org',
        ),
    )
    parser.add_argument(
        '--git-project',
        action='store',
        type=str,
        default=get_env_var(
            key='git_project',
            default='almalinux/pungi-almalinux',
        ),
    )
    parser.add_argument(
        '--git-type',
        action='store',
        type=str,
        default=get_env_var(key='git_type', default='gitea'),
    )
    parser.add_argument(
        '--sign-service-username',
        action='store',
        help='An username of a sign service',
        default=get_env_var(key='sign_service_username'),
    )
    parser.add_argument(
        '--sign-service-password',
        action='store',
        help='A password of a sign service',
        default=get_env_var(key='sign_service_password'),
    )
    parser.add_argument(
        '--sign-service-endpoint',
        action='store',
        help='An endpoint of a sign service',
        default=get_env_var(key='sign_service_endpoint'),
    )
    parser.add_argument(
        '-e',
        '--koji-excluded-packages',
        required=False,
        nargs='+',
        type=List[str],
        default=get_env_var(
            key='koji_excluded_packages',
            default='',
            is_multiline=True,
        ),
    )
    parser.add_argument(
        '--branch',
        action=StoreAction,
        type=str,
        default=get_env_var(key='branch', default='master'),
    )
    return parser


def main():

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    sensitive_arguments = (
        'git_auth_token',
        'sign_service_password',
    )
    args = create_parser().parse_args()
    logging.info('All CLI arguments:')
    for arg_name, arg_value in vars(args).items():
        if arg_name in sensitive_arguments:
            continue
        logging.info('%s: %s', arg_name, arg_value)
    runner = Runner(
        working_root_directory=args.working_root_directory,
        product_name=args.product_name,
        distribution_major_version=args.distribution_major_version,
        distribution_minor_version=args.distribution_minor_version,
        arch=args.arch,
        branch=args.branch,
        keep_builds=args.keep_builds,
        use_products_repos=args.use_products_repos,
        env_files=args.env_files,
        beta_suffix=args.beta_suffix,
        sigkeys_fingerprints=args.sigkeys_fingerprints,
        skip_mirroring=args.skip_mirroring,
        local_repos=args.local_repos,
        not_needed_variant=args.not_needed_variant,
        pgp_sign_keyid=args.pgp_sign_keyid,
        git_url=args.git_url,
        git_project=args.git_project,
        git_auth_token=args.git_auth_token,
        git_auth_username=args.git_auth_username,
        git_type=args.git_type,
        sign_service_username=args.sign_service_username,
        sign_service_password=args.sign_service_password,
        sign_service_endpoint=args.sign_service_endpoint,
        koji_excluded_packages=args.koji_excluded_packages,
    )
    try:
        runner.checkout_scripts()
        runner.prepare()
        runner.build()
        runner.post()
    finally:
        runner.cleanup()


if __name__ == '__main__':
    main()
