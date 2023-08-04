#!/usr/bin/env python3
# coding=utf-8
import argparse
import base64
import json
import logging
import os
import subprocess
from configparser import ConfigParser
from pathlib import Path
from typing import (
    List,
    Dict, Optional,
)

import jinja2
import requests

from urllib.parse import quote, quote_plus
from requests.auth import HTTPBasicAuth

VARIANTS_GENERATOR_FOLDER = 'variants-xml-generator'
COMPS_GENERATOR_FOLDER = 'almacomps'
KOJI_CONF_PATH = '/etc/koji.conf'

VARIANTS_OPTIONS_FILENAME = 'variants_options.json'
PUNGI_BUILD_CONF_TEMPLATE_FILENAME = 'pungi-build.conf.j2'
PUNGI_BUILD_CONF_FILENAME = 'pungi-build.conf'
INCLUDE_EXCLUDE_CONF_FILENAME = 'include_exclude.conf'
MULTILIB_CONF_FILENAME = 'multilib.conf'
EXTRA_OPTIONS_CONF_FILENAME = 'extra_options.conf'


logging.basicConfig(level=logging.INFO)


def dnf_reposync_mirroring(
        use_products_repos: bool,
        product_name: str,
        distribution_major_version: str,
        arch: str,
        mirroring_target: str
) -> None:
    base_repos_dir = Path('/etc/yum.repos.d/').joinpath(
        product_name.lower(),
        distribution_major_version,
        arch,
    )
    specific_repos = base_repos_dir.joinpath('specific_repos')
    products_repos = base_repos_dir.joinpath('products_repos')
    platform_repos = base_repos_dir.joinpath('platform_repos')
    if use_products_repos and any(products_repos.iterdir()):
        command = f'dnf reposync -p {mirroring_target}-products_repos ' \
                  f'--setopt=reposdir="{products_repos}" ' \
                  '--enablerepo=* --download-metadata ' \
                  '--delete --downloadcomps --remote-time '
        subprocess.check_call(
            command,
            shell=True,
        )
    if any(specific_repos.iterdir()):
        command = f'dnf reposync -p {mirroring_target} ' \
                  f'--setopt=reposdir="{specific_repos}" ' \
                  '--enablerepo=* --download-metadata ' \
                  '--delete --downloadcomps --remote-time '
        subprocess.check_call(
            command,
            shell=True,
        )
    if any(platform_repos.iterdir()):
        command = f'dnf reposync -p {mirroring_target} ' \
                  f'--setopt=reposdir="{platform_repos}" ' \
                  '--enablerepo=* --download-metadata ' \
                  '--delete --downloadcomps --remote-time '
        subprocess.check_call(
            command,
            shell=True,
        )


def load_remote_file_content(
        name: str,
        distribution_major_version: int,
        distribution_minor_version: int,
        beta_suffix: str,
        product_name: str,
        git_auth_token: str,
        git_auth_username: str,
        git_url: str,
        git_project: str,
        git_type: str = 'gitea',

) -> Optional[str]:
    beta_suffix = beta_suffix if beta_suffix else ''
    decoding_func = {
        'gerrit': lambda content: base64.b64decode(content).decode('utf-8'),
        'gitea': lambda content: base64.b64decode(json.loads(content.decode())
                                                  ['content']).decode('utf-8'),
        'github': lambda content: base64.b64decode(content).decode('utf-8'),
    }
    if 'gerrit' == git_type:
        name = quote(name, safe='')
        url = f'https://{git_url}/a/projects/{git_project}/branches/' \
              f'{product_name[0].lower()}{distribution_major_version}.' \
              f'{distribution_minor_version}' \
              f'{beta_suffix}/files/{name}/content'
        response = requests.get(url, auth=HTTPBasicAuth(
            username=git_auth_username,
            password=git_auth_token,
        ))
    elif 'gitea' == git_type:
        headers = {
            'accept': 'application/json',
        }
        params = {
            'access_token': git_auth_token,
            'ref': (
                f'{product_name[0].lower()}{distribution_major_version}.'
                f'{distribution_minor_version}{beta_suffix}'
            )
        }
        name = quote(name, safe='')
        url = f'https://{git_url}/api/v1/repos/{git_project}/contents/{name}'
        response = requests.get(url, params=params, headers=headers)
    elif 'github' == git_type:
        name = quote(name, safe='')
        headers = {
            'Authorization:': f'Bearer {git_auth_token}',
            'Accept': 'application/vnd.github+json',
        }
        params = {
            'ref': (
                f'{product_name[0].lower()}{distribution_major_version}.'
                f'{distribution_minor_version}{beta_suffix}'
            )
        }
        url = f'https://api.github/repos/{git_project}/contents/{name}'
        response = requests.get(url, params=params, headers=headers)
    else:
        raise NotImplemented(f'{git_type} is not supported yet')
    try:
        response.raise_for_status()
    except requests.RequestException:
        return
    return decoding_func[git_type](response.content)


def render_variants_options(
        env: jinja2.Environment,
        variables: Dict,
) -> dict:
    variants_options_template = env.get_template(os.path.join(
        variables['arch'],
        VARIANTS_OPTIONS_FILENAME,
    ))
    variants_options = variants_options_template.render(**variables)
    return json.loads(variants_options)


def render_pungi_build_conf(
        env: jinja2.Environment,
        variables: Dict,
) -> str:
    pungi_build_conf_template = env.get_template(
        PUNGI_BUILD_CONF_TEMPLATE_FILENAME,
    )
    return pungi_build_conf_template.render(**variables)


def prepare_build_conf(
        product_name: str,
        arch: str,
        distribution_major_version: int,
        distribution_minor_version: int,
        env_path: str,
        sigkeys_fingerprints: List[str],
        git_url: str,
        git_project: str,
        git_auth_token: str,
        git_auth_username: str,
        git_type: str = 'gitea',
        beta_suffix: str = '',
):
    logging.info(
        'Prepare build conf'
    )
    variables = {
        'product_name': product_name,
        'arch': arch,
        'distribution_major_version': distribution_major_version,
        'distribution_minor_version': distribution_minor_version,
        'beta_suffix': beta_suffix,
        'sigkeys_fingerprints': [
            f'"{sigkey}"' for sigkey in sigkeys_fingerprints if sigkey
        ],
        'git_auth_username': quote_plus(git_auth_username),
        'git_auth_token': quote_plus(git_auth_token),
    }
    env = jinja2.Environment(
        loader=jinja2.FunctionLoader(lambda name: load_remote_file_content(
            name=name,
            distribution_major_version=distribution_major_version,
            distribution_minor_version=distribution_minor_version,
            beta_suffix=beta_suffix,
            git_url=git_url,
            git_project=git_project,
            git_auth_token=git_auth_token,
            git_auth_username=git_auth_username,
            product_name=product_name,
            git_type=git_type,
        )),
        autoescape=jinja2.select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    variables['variants'] = render_variants_options(
        env=env,
        variables=variables,
    )
    extra_options_conf_lines = load_remote_file_content(
        name=f'{arch}/{EXTRA_OPTIONS_CONF_FILENAME}',
        distribution_minor_version=distribution_minor_version,
        distribution_major_version=distribution_major_version,
        beta_suffix=beta_suffix,
        git_url=git_url,
        git_project=git_project,
        git_auth_token=git_auth_token,
        git_auth_username=git_auth_username,
        product_name=product_name,
        git_type=git_type,
    )
    variables['extra_options'] = extra_options_conf_lines is not None
    pungi_build_conf_lines = render_pungi_build_conf(
        env=env,
        variables=variables,
    )
    include_exclude_conf_lines = load_remote_file_content(
        name=f'{arch}/{INCLUDE_EXCLUDE_CONF_FILENAME}',
        distribution_minor_version=distribution_minor_version,
        distribution_major_version=distribution_major_version,
        beta_suffix=beta_suffix,
        git_url=git_url,
        git_project=git_project,
        git_auth_token=git_auth_token,
        git_auth_username=git_auth_username,
        product_name=product_name,
        git_type=git_type,
    )
    multilib_conf_lines = load_remote_file_content(
        name=f'{arch}/{MULTILIB_CONF_FILENAME}',
        distribution_minor_version=distribution_minor_version,
        distribution_major_version=distribution_major_version,
        beta_suffix=beta_suffix,
        git_url=git_url,
        git_project=git_project,
        git_auth_token=git_auth_token,
        git_auth_username=git_auth_username,
        product_name=product_name,
        git_type=git_type,
    )
    with open(os.path.join(
            env_path,
            PUNGI_BUILD_CONF_FILENAME,
    ), 'w') as fd:
        fd.write(pungi_build_conf_lines)
    with open(os.path.join(
            env_path,
            INCLUDE_EXCLUDE_CONF_FILENAME,
    ), 'w') as fd:
        fd.write(include_exclude_conf_lines)
    with open(os.path.join(
            env_path,
            MULTILIB_CONF_FILENAME,
    ), 'w') as fd:
        fd.write(multilib_conf_lines)
    if variables['extra_options']:
        with open(os.path.join(
                env_path,
                EXTRA_OPTIONS_CONF_FILENAME,
        ), 'w') as fd:
            fd.write(extra_options_conf_lines)


def add_koji_profile(
        env_path: str,
        profile_name: str,
):
    logging.info(
        'Add koji profile "%s" to "%s"',
        profile_name,
        KOJI_CONF_PATH,
    )
    koji_env_path = os.path.join(
        env_path,
        'koji'
    )
    with open(KOJI_CONF_PATH, 'r') as koji_conf_file:
        koji_conf_obj = ConfigParser()
        koji_conf_obj.read_file(koji_conf_file)
    if profile_name not in koji_conf_obj.sections():
        koji_conf_obj.add_section(profile_name)
    koji_conf_obj.set(profile_name, 'topdir', koji_env_path)
    with open(KOJI_CONF_PATH, 'w') as koji_conf_file:
        koji_conf_obj.write(koji_conf_file)


def save_additional_env_files(
        env_path: str,
        add_env_files: List[str],
) -> None:
    for add_env_file in filter(lambda i: True if i else False, add_env_files):
        env_file_name, file_content_in_base64 = add_env_file.split(',')
        env_file_content = base64.b64decode(
            file_content_in_base64,
        ).decode('utf-8')
        env_file_path = os.path.join(
            env_path,
            env_file_name,
        )
        with open(env_file_path, 'w') as env_file:
            env_file.write(env_file_content)


def create_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--env-path',
        action='store',
        help='A path to folder which will be used '
             'for building new distribution',
        required=False,
        default=None,
    )

    subparsers = parser.add_subparsers(
        dest='command',
    )

    parser_synchronize_using_dnf_reposync = subparsers.add_parser(
        'dnf_reposync_synchronize',
        help='Run synchronize using DNF reposync',
    )

    parser_synchronize_using_dnf_reposync.add_argument(
        '--mirroring-dnf-repos',
        nargs='*',
        type=str,
        help='A list of repos which will be mirrored',
        required=False,
    )
    parser_synchronize_using_dnf_reposync.add_argument(
        '--mirroring-target',
        action='store',
        help='A folder which will contain a local mirror',
        required=False,
    )
    parser_synchronize_using_dnf_reposync.add_argument(
        '--use-products-repos',
        action='store_true',
        default=False,
    )
    parser_synchronize_using_dnf_reposync.add_argument(
        '--product-name',
        action='store',
        help='A name of building product',
        required=True,
    )
    parser_synchronize_using_dnf_reposync.add_argument(
        '--arch',
        help='Architecture of a product',
        action='store',
        required=True,
    )
    parser_synchronize_using_dnf_reposync.add_argument(
        '--distribution-major-version',
        help='Major version of a product',
        action='store',
        required=True,
    )

    parser_add_env_files = subparsers.add_parser(
        'add_env_files',
        help='Save environment files which are passed as base64 strings'
    )
    parser_add_env_files.add_argument(
        '--env-files',
        nargs='*',
        type=str,
        help='A list of files which should be stored in env '
             'directory. E.t. `add-comps.xml,<content_in_base64>`',
        required=False,
        default=[],
    )

    parser_koji_profile = subparsers.add_parser(
        'add_koji_profile',
        help=f'Add new koji profile to {KOJI_CONF_PATH}',
    )
    parser_koji_profile.add_argument(
        '--koji-profile-name',
        action='store',
        help='A name of koji profile',
        required=True,
    )

    parser_build_conf = subparsers.add_parser(
        'prepare_build_conf',
        help='Prepare a Pungi build conf',
    )
    parser_build_conf.add_argument(
        '--product-name',
        action='store',
        help='A name of building product',
        required=True,
    )
    parser_build_conf.add_argument(
        '--arch',
        help='Architecture of a product',
        action='store',
        required=True,
    )
    parser_build_conf.add_argument(
        '--distribution-major-version',
        help='Major version of a product',
        action='store',
        required=True,
    )
    parser_build_conf.add_argument(
        '--distribution-minor-version',
        help='Minor version of a product',
        action='store',
        required=True,
    )
    parser_build_conf.add_argument(
        '--beta-suffix',
        help='Suffix of a ISOs & Volume ID names. E.g. `-beta-1`',
        action='store',
        default='',
        type=str,
        required=False,
    )
    parser_build_conf.add_argument(
        '--sigkeys-fingerprints',
        nargs='*',
        type=str,
        help='A list of fingerprints of AlmaLinux sign keys. '
             'They are used for checking that all packages are signed',
    )
    parser_build_conf.add_argument(
        '--git-auth-token',
        action='store',
        type=str,
        help='Auth token for access to a Git repository which '
             'contains a build config and related stuff'
    )
    parser_build_conf.add_argument(
        '--git-auth-username',
        action='store',
        type=str,
        help='Auth username for access to a Git repository which '
             'contains a build config and related stuff'
    )
    parser_build_conf.add_argument(
        '--git-url',
        action='store',
        type=str,
        help='Git URL for a Git repository which '
             'contains a build config and related stuff'
    )
    parser_build_conf.add_argument(
        '--git-project',
        action='store',
        type=str,
        help='Name of a Git repository which '
             'contains a build config and related stuff'
    )
    parser_build_conf.add_argument(
        '--git-type',
        action='store',
        type=str,
        default='gitea',
        help='Type of a Git repository which '
             'contains a build config and related stuff'
    )
    return parser


def check_is_root():
    if os.geteuid():
        logging.error('The script should be ran under root or any sudo user')
        exit(1)


def cli_main():
    # check_is_root()
    parser = create_parser()
    args = parser.parse_args()
    if args.command == 'dnf_reposync_synchronize':
        dnf_reposync_mirroring(
            use_products_repos=args.use_products_repos,
            product_name=args.product_name,
            distribution_major_version=args.distribution_major_version,
            arch=args.arch,
            mirroring_target=args.mirroring_target,
        )
    else:
        # another commands which require an env path
        os.makedirs(args.env_path, exist_ok=True)
    if args.command == 'add_env_files':
        save_additional_env_files(
            env_path=args.env_path,
            add_env_files=args.env_files,
        )
    if args.command == 'add_koji_profile':
        add_koji_profile(
            env_path=args.env_path,
            profile_name=args.koji_profile_name,
        )
    if args.command == 'prepare_build_conf':
        prepare_build_conf(
            beta_suffix=args.beta_suffix,
            product_name=args.product_name,
            arch=args.arch,
            distribution_major_version=args.distribution_major_version,
            distribution_minor_version=args.distribution_minor_version,
            env_path=args.env_path,
            sigkeys_fingerprints=args.sigkeys_fingerprints,
            git_url=args.git_url,
            git_project=args.git_project,
            git_auth_token=args.git_auth_token,
            git_auth_username=args.git_auth_username,
            git_type=args.git_type,
        )


if __name__ == '__main__':
    cli_main()
