#!/usr/bin/env python3
# coding=utf-8
import json
import os
import logging
from collections import defaultdict
from shutil import (
    rmtree,
    copytree,
    copy,
)

import argparse
import requests

from subprocess import check_call
from configparser import ConfigParser
from time import time
from typing import (
    List,
    Optional, 
    Dict,
)
from pathlib import Path
from urllib.parse import urljoin
from requests.auth import AuthBase


PUNGI_RESULTS = 'pungi-results'
KICKSTART_REPO = 'BaseOS'
INCLUDED_TO_KICKSTART_REPO = 'AppStream'

PATH_DICTIONARY = defaultdict(lambda: None, **{
    'debug': 'debug/{arch}',
    'source': 'Source',
    'source_packages': 'Source/Packages',
    'source_repository': 'Source',
    'source_tree': 'Source',
    'debug_packages': 'debug/{arch}/Packages',
    'debug_repository': 'debug/{arch}',
    'debug_tree': 'debug/{arch}',
})  # type: Dict[str ,Optional[str]]


logging.basicConfig(level=logging.INFO)


class BearerAuth(AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, request):
        request.headers["Authorization"] = f'Bearer {self.token}'
        return request


class Signer:
    __session__ = None  # type: Optional[requests.Session]

    def get_token(self, username, password) -> str:
        data = {
            'email': username,
            'password': password
        }
        response = requests.post(
            url=urljoin(self.endpoint + '/', 'token'),
            json=data,
        )
        response.raise_for_status()
        return response.json()['token']

    def __init__(self, username, password, endpoint):
        self.endpoint = endpoint
        self.token = self.get_token(
            username=username,
            password=password,
        )

    def sign(
            self,
            file_path: Path,
            keyid: str,
            sign_type: str = 'detach-sign',
    ) -> Path:
        auth = BearerAuth(token=self.token)
        params = {
            'keyid': keyid,
            'sign_type': sign_type,
        }
        files = {
            'file': file_path.open('rb'),
        }
        response = requests.post(
            url=urljoin(self.endpoint + '/', 'sign'),
            params=params,
            files=files,
            auth=auth,
        )
        response.raise_for_status()
        if sign_type == 'detach-sign':
            file_path = file_path.with_suffix(file_path.suffix + '.asc')
        with file_path.open('w') as fd:
            fd.write(response.text)
        return file_path

    @staticmethod
    def verify(file_path: Path):
        if file_path.suffix == '.asc':
            command = f'gpg --verify {file_path} {file_path.with_suffix("")}'
        else:
            command = f'gpg --verify {file_path}'
        check_call(
            command,
            shell=True,
            universal_newlines=True,
        )


def move_sources_folder_to_right_place(
        latest_path: Path,
        repo_name: str,
):
    src_of_sources = latest_path.joinpath(repo_name, 'source')
    dst_of_sources = latest_path.joinpath(repo_name, PATH_DICTIONARY['source'])
    if src_of_sources.exists():
        logging.info(
            'Move sources to right place for result '
            'dir "%s" and repo "%s"',
            latest_path,
            repo_name,
        )
        src_of_sources.joinpath('tree').rename(dst_of_sources)
        rmtree(src_of_sources)


def move_debug_folder_to_right_place(
        latest_path: Path,
        repo_name: str,
        arch: str,
):
    src_of_debug = latest_path.joinpath(repo_name, arch, 'debug')
    dst_of_debug = latest_path.joinpath(
        repo_name,
        PATH_DICTIONARY['debug'].format(arch=arch),
    )
    if src_of_debug.exists():
        logging.info(
            'Move a folder with debug rpms to right places for '
            'result dir "%s", arch "%s" and repo "%s"',
            latest_path,
            arch,
            repo_name,
        )
        os.makedirs(dst_of_debug.parent, exist_ok=True)
        src_of_debug.joinpath('tree').rename(dst_of_debug)
        rmtree(src_of_debug)


def copy_updateinfo_from_platform_repos(
        src_repos_path: Path,
        latest_path: Path,
        repo_name: str,
        arch: str,
):
    dst_path = latest_path.joinpath(repo_name, arch, 'os')
    if not dst_path.exists():
        return
    for path in src_repos_path.glob(
            f'platform-almalinux-[0-9]-{repo_name.lower()}-'
            f'{arch}/repodata/*updateinfo*'
    ):
        dst_file = dst_path.joinpath('repodata', path.name)
        if dst_file.exists():
            return
        logging.info('Copy updateinfo.xml for repo "%s"', repo_name)
        copy(
            path,
            dst_file,
        )
        dst_repodata_path = dst_path.joinpath('repodata')
        logging.info('Modify repo "%s" with updateinfo.xml', repo_name)
        check_call(
            f'modifyrepo_c --mdtype=updateinfo {dst_file} {dst_repodata_path}',
            shell=True,
        )
        return
    logging.warning(
        'Updateinfo.xml for repo "%s" does not exist',
        repo_name,
    )


def sign_repomd_xml(
        latest_path: Path,
        repo_name: str,
        arch: str,
        pgp_keyid: str,
        username: str,
        password: str,
        endpoint: str,
):
    repomd_xml_path_suffix = 'repodata/repomd.xml'
    os_repomd_xml_path = latest_path.joinpath(
        repo_name,
        arch,
        'os',
        repomd_xml_path_suffix,
    )
    kickstart_repomd_xml_path = latest_path.joinpath(
        repo_name,
        arch,
        'kickstart',
        repomd_xml_path_suffix,
    )
    source_repomd_xml_path = latest_path.joinpath(
        repo_name,
        PATH_DICTIONARY['source'],
        repomd_xml_path_suffix,
    )
    debug_repomd_xml_path = latest_path.joinpath(
        repo_name,
        PATH_DICTIONARY['debug'].format(arch=arch),
        repomd_xml_path_suffix
    )
    logging.info(
        'Sign repomd.xml files for "%s" and verify signatures',
        repo_name,
    )
    for repomd_xml_path in (
        os_repomd_xml_path,
        kickstart_repomd_xml_path,
        source_repomd_xml_path,
        debug_repomd_xml_path,
    ):
        if not repomd_xml_path.exists():
            continue
        signer = Signer(
            username=username,
            password=password,
            endpoint=endpoint,
        )
        file_path = signer.sign(
            file_path=repomd_xml_path,
            keyid=pgp_keyid,
        )
        signer.verify(file_path=file_path)


def create_kickstart_folder(
        latest_path: Path,
        repo_name: str,
        arch: str,
):
    src_kickstart = latest_path.joinpath(repo_name, arch, 'os')
    dst_kickstart = latest_path.joinpath(repo_name, arch, 'kickstart')
    if src_kickstart.exists() and not dst_kickstart.exists():
        logging.info(
            'Make kickstart repo for result dir "%s", '
            'repo "%s" and arch "%s"',
            latest_path,
            repo_name,
            arch,
        )
        copytree(
            src_kickstart,
            dst_kickstart,
            copy_function=os.link,
        )
        logging.info(
            'Copy repodata for a kickstart without using hardlinks'
        )
        repodata_dst_path = dst_kickstart.joinpath('repodata')
        repodata_src_path = src_kickstart.joinpath('repodata')
        rmtree(repodata_dst_path)
        copytree(
            repodata_src_path,
            repodata_dst_path,
        )


def update_timestamp_in_treeinfo(
        tree_info_path: Path,
        timestamp: int,
):
    replaced_values = {
        'general': 'timestamp',
        'tree': 'build_timestamp',
    }
    if not tree_info_path.exists():
        return
    tree_info_config = ConfigParser()
    tree_info_config.read(tree_info_path)
    for section, key in replaced_values.items():
        tree_info_config.set(
            section=section,
            option=key,
            value=str(timestamp),
        )
    logging.info(
        'Update timestamp "%s" in .treeinfo for "%s"',
        timestamp,
        tree_info_path,
    )
    with open(tree_info_path, 'w') as tree_info_fp:
        tree_info_config.write(tree_info_fp)


def update_kickstart_treeinfo_file(
        tree_info_path: str,
):
    replaced_values = {
        'packages': None,
        'repository': None,
    }
    tree_info_config = ConfigParser()
    tree_info_config.read(tree_info_path)
    logging.info(
        'Update .treeinfo file "%s": replace path-suffix `os` by `kickstart`',
        tree_info_path,
    )
    section_name = f'variant-{INCLUDED_TO_KICKSTART_REPO}'
    for key in replaced_values:
        if section_name not in tree_info_config.sections():
            continue
        replaced_values[key] = tree_info_config.get(
            section=section_name,
            option=key
        ).replace('os', 'kickstart')
    for key, value in replaced_values.items():
        if section_name not in tree_info_config.sections():
            continue
        tree_info_config.set(
            section=section_name,
            option=key,
            value=value,
        )
    # because it's hardlink and could be modified
    # both files (in dirs `os` and `kickstart`)
    os.remove(tree_info_path)

    with open(tree_info_path, 'w') as tree_info_fp:
        tree_info_config.write(tree_info_fp)


def sign_isos_checksum(
        latest_path: Path,
        arch: str,
        pgp_keyid: str,
        username: str,
        password: str,
        endpoint: str,
):
    logging.info('Sign ISOs CHECKSUM and verify signature')
    checksum_path = latest_path.joinpath('isos', arch, 'CHECKSUM')
    if not checksum_path.exists():
        logging.warning('File CHECKSUM is absent')
        return
    signer = Signer(
        username=username,
        password=password,
        endpoint=endpoint,
    )
    file_path = signer.sign(
        file_path=checksum_path,
        keyid=pgp_keyid,
        sign_type='clear-sign',
    )
    signer.verify(file_path=file_path)


def post_processing_images_json_metadata(
        latest_path: Path,
        arch: str,
):
    images_json_path = latest_path.joinpath(
        'metadata', arch, 'images.json'
    )
    logging.info('Post-processing images.json')
    if not images_json_path.exists():
        logging.warning('images.json is absent')
        return
    with open(images_json_path, 'r') as images_metadata_fd:
        content = json.load(images_metadata_fd)
        images = content['payload']['images']
        for variant in images:
            variant_data = images[variant]  # type: Dict[str, List[Dict]]
            for arch, images_list in variant_data.items():
                variant_data[arch] = [
                    dict(
                        image,
                        **{
                            'path': str(Path('isos').joinpath(
                                arch,
                                Path(image['path']).name,
                            ))
                        }
                    ) for image in images_list
                ]

    with open(images_json_path, 'w') as images_metadata_fd:
        json.dump(
            content,
            images_metadata_fd,
            indent=4,
        )


def post_processing_rpms_json_metadata(
        latest_path: Path,
        arch: str,
):
    rpms_json_path = latest_path.joinpath(
        'metadata', arch, 'rpms.json'
    )
    logging.info('Post-processing rpms.json')
    if not rpms_json_path.exists():
        logging.warning('rpms.json is absent')
        return
    with open(rpms_json_path, 'r') as rpms_metadata_fd:
        content = json.load(rpms_metadata_fd)
        rpms = content['payload']['rpms']
        for variant in rpms:
            variant_data = rpms[variant]
            if variant == 'Minimal':
                continue
            for arch in variant_data:
                arch_data = variant_data[arch]
                for srpm in arch_data:
                    srpm_data = arch_data[srpm]
                    for artifact in srpm_data:
                        artifact_data = srpm_data[artifact]
                        path_suffix = PATH_DICTIONARY[
                            artifact_data['category']
                        ]  # type: Optional[str]
                        if path_suffix is None:
                            continue
                        else:
                            path_suffix = path_suffix.format(arch=arch)
                        artifact_path = Path(artifact_data['path'])
                        artifact_data['path'] = str(Path(variant).joinpath(
                            path_suffix,
                            artifact_path.parent.name,
                            artifact_path.name,
                        ))

    with open(rpms_json_path, 'w') as rpms_metadata_fd:
        if 'Minimal' in content['payload']['rpms']:
            del content['payload']['rpms']['Minimal']
        json.dump(
            content,
            rpms_metadata_fd,
            indent=4,
        )


def post_processing_compose_info_json_metadata(
        latest_path: Path,
        arch: str,
):
    composeinfo_json_path = latest_path.joinpath(
        'metadata', arch, 'composeinfo.json'
    )

    logging.info('Post-processing composeinfo.json')
    if not composeinfo_json_path.exists():
        logging.warning('composeinfo.json is absent')
        return
    with open(composeinfo_json_path, 'r') as composeinfo_metadata_fd:
        content = json.load(composeinfo_metadata_fd)
        variants = content['payload']['variants']
        for variant in variants:
            variant_paths = variants[variant]['paths']
            if variant == 'Minimal':
                continue
            for path_type in variant_paths:
                path_data = variant_paths[path_type]  # type: Dict
                for arch, path in path_data.items():
                    path_suffix = PATH_DICTIONARY[
                        path_type]  # type: Optional[str]
                    if path_suffix is None:
                        continue
                    else:
                        path_suffix = path_suffix.format(arch=arch)
                    path = Path(variant).joinpath(path_suffix)
                    path_data[arch] = str(path)

    with open(composeinfo_json_path, 'w') as composeinfo_metadata_fd:
        if 'Minimal' in content['payload']['variants']:
            del content['payload']['variants']['Minimal']
        json.dump(
            content,
            composeinfo_metadata_fd,
            indent=4,
        )


def move_json_metadata_to_arch_folder(
        latest_path: Path,
        arch: str,
):
    extension = '*.json'
    metadata_path = latest_path.joinpath('metadata')
    metadata_arch_path = metadata_path.joinpath(arch)
    os.makedirs(metadata_arch_path, exist_ok=True)
    for json_metadata in Path(metadata_path).glob(extension):
        logging.info(
            'Copy "%s" to arch directory "%s"',
            json_metadata,
            metadata_arch_path,
        )
        json_metadata.rename(metadata_arch_path.joinpath(json_metadata.name))


def move_iso_and_its_artifacts_to_isos_arch_folder(
        src_latest_path: Path,
        repo_name: str,
        arch: str,
        exts_of_files: List[str],
        dst_latest_path: Optional[Path] = None,
):
    src_iso_folder_path = src_latest_path.joinpath(repo_name, arch, 'iso')
    isos_arch_folder = (dst_latest_path or src_latest_path).joinpath(
        'isos',
        arch,
    )
    os.makedirs(isos_arch_folder, exist_ok=True)
    if not src_iso_folder_path.exists():
        return
    for ext_of_file in exts_of_files:
        for src_file_path in src_iso_folder_path.glob(ext_of_file):
            dst_file_path = isos_arch_folder.joinpath(src_file_path.name)
            if not src_file_path.exists():
                continue
            if dst_file_path.exists():
                continue
            logging.info(
                'Move iso or iso\'s artifacts from "%s" to "%s"',
                src_file_path,
                dst_file_path,
            )
            src_file_path.rename(dst_file_path)
    src_checksum_path = src_latest_path.joinpath(
        repo_name,
        arch,
        'iso',
        'CHECKSUM',
    )
    dst_checksum_path = isos_arch_folder.joinpath('CHECKSUM')
    if src_checksum_path.exists():
        logging.info(
            'Write CHEKSUM from "%s" to "%s"',
            src_checksum_path,
            dst_checksum_path,
        )
        with open(src_checksum_path, 'r') as src_checksum_file, \
             open(dst_checksum_path, 'a+') as dst_checksum_path:
            src_checksum_content = src_checksum_file.read()
            dst_checksum_path.write(src_checksum_content)
    rmtree(src_iso_folder_path)


def rename_latest_dir(
        latest_path: Path,
):
    old_real_name = Path(os.readlink(latest_path.parent)).name
    if not old_real_name.startswith('last_compose_dir'):
        return
    old_real_name_path = latest_path.parent.parent.joinpath(old_real_name)
    new_real_name = f'{int(time())}-{old_real_name}'
    new_real_name_path = latest_path.parent.parent.joinpath(new_real_name)
    logging.info('New real name path %s', new_real_name_path)
    logging.info('Old real name path %s', old_real_name_path)
    if not old_real_name_path.exists():
        return
    logging.info(
        'Add the timestamp to name of a '
        'real directory with latest result: "%s"',
        new_real_name_path,
    )
    old_real_name_path.rename(new_real_name_path)
    os.unlink(latest_path.parent)
    os.symlink(new_real_name_path, latest_path.parent)


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
        '--sign-service-username',
        action='store',
        help='An username of a sign service',
        default=None,
        required=False,
    )
    parser.add_argument(
        '--sign-service-password',
        action='store',
        help='A password of a sign service',
        default=None,
        required=False,
    )
    parser.add_argument(
        '--sign-service-endpoint',
        action='store',
        help='An endpoint of a sign service',
        default=None,
        required=False,
    )
    parser.add_argument(
        '--pgp-sign-keyid',
        action='store',
        help='PGP sign key ID. Used for signing building artifacts',
        required=False,
        default=None,
    )
    parser.add_argument(
        '--middle-result-directory',
        action='store',
        help='A directory with middle result. '
             'E.g. a directory contains Minimal iso',
        default=None,
        required=False,
    )
    parser.add_argument(
        '--arch',
        type=str,
        help='Architecture of a distribution',
        required=True,
    )
    parser.add_argument(
        '--source-repos-folder',
        type=str,
        help='Path to folder there are stored source repos',
        required=True,
    )
    parser.add_argument(
        '--repos',
        nargs='+',
        type=str,
        help='A list of repositories are contained in distribution',
        required=True,
    )
    parser.add_argument(
        '--middle-repos',
        nargs='+',
        type=str,
        help='A list of repositories from a middle result '
             'which will be used for getting ISOs',
        required=False,
        default=[],
    )
    parser.add_argument(
        '--not-needed-repos',
        nargs='*',
        type=str,
        help='A list of repositories which are not needed, e.g. Minimal',
        required=False,
        default=[],
    )

    return parser


def cli_main():

    args = create_parser().parse_args()
    pungi_results = Path(args.env_path).joinpath(PUNGI_RESULTS)
    latest_result_paths = pungi_results.glob('latest-*')
    logging.info(
        'We have the following latest results "%s"',
        list(latest_result_paths),
    )
    extensions_of_files = ['*.iso', '*.manifest']
    for latest_path in latest_result_paths:
        latest_path = latest_path.joinpath('compose')
        build_timestamp = int(time())

        for repo in args.repos:
            if not latest_path.joinpath(repo).exists():
                continue
            if repo in args.middle_repos:
                not_needed_repo_path = latest_path.joinpath(repo)
                if not_needed_repo_path.exists():
                    rmtree(not_needed_repo_path)
                continue
            move_sources_folder_to_right_place(
                latest_path=latest_path,
                repo_name=repo,
            )
            move_debug_folder_to_right_place(
                latest_path=latest_path,
                repo_name=repo,
                arch=args.arch,
            )
            copy_updateinfo_from_platform_repos(
                src_repos_path=Path(args.source_repos_folder),
                latest_path=latest_path,
                repo_name=repo,
                arch=args.arch,
            )
            create_kickstart_folder(
                latest_path=latest_path,
                repo_name=repo,
                arch=args.arch,
            )
            if all(opt is not None for opt in (
                args.sign_service_username,
                args.sign_service_password,
                args.sign_service_endpoint
            )):
                sign_repomd_xml(
                    latest_path=latest_path,
                    repo_name=repo,
                    arch=args.arch,
                    username=args.sign_service_username,
                    password=args.sign_service_password,
                    endpoint=args.sign_service_endpoint,
                    pgp_keyid=args.pgp_sign_keyid,
                )
            move_iso_and_its_artifacts_to_isos_arch_folder(
                src_latest_path=latest_path,
                repo_name=repo,
                arch=args.arch,
                exts_of_files=extensions_of_files,
            )
            repo_path = latest_path.joinpath(repo)
            for path in Path(repo_path).rglob('.treeinfo'):
                update_timestamp_in_treeinfo(
                    tree_info_path=path,
                    timestamp=build_timestamp,
                )
                if path.parent.name == 'kickstart':
                    update_kickstart_treeinfo_file(
                        tree_info_path=str(path),
                    )
        move_json_metadata_to_arch_folder(
            latest_path=latest_path,
            arch=args.arch,
        )
        post_processing_compose_info_json_metadata(
            latest_path=latest_path,
            arch=args.arch,
        )
        post_processing_rpms_json_metadata(
            latest_path=latest_path,
            arch=args.arch,
        )
        post_processing_images_json_metadata(
            latest_path=latest_path,
            arch=args.arch,
        )
        if all(opt is not None for opt in (
            args.sign_service_username,
            args.sign_service_password,
            args.sign_service_endpoint
        )):
            sign_isos_checksum(
                latest_path=latest_path,
                arch=args.arch,
                username=args.sign_service_username,
                password=args.sign_service_password,
                endpoint=args.sign_service_endpoint,
                pgp_keyid=args.pgp_sign_keyid,
            )
        for repo in args.middle_repos:
            if args.middle_result_directory is not None:
                move_iso_and_its_artifacts_to_isos_arch_folder(
                    src_latest_path=Path(
                        args.middle_result_directory,
                    ).joinpath('compose'),
                    repo_name=repo,
                    arch=args.arch,
                    exts_of_files=extensions_of_files,
                    dst_latest_path=latest_path,
                )
        for repo in args.not_needed_repos:
            not_needed_repo_path = latest_path.joinpath(repo)
            if not_needed_repo_path.exists():
                logging.info(
                    'Remove not needed variant "%s" by path "%s"',
                    repo,
                    not_needed_repo_path,
                )
                rmtree(not_needed_repo_path)
        rename_latest_dir(latest_path=latest_path)
    if args.middle_result_directory is not None and \
            Path(args.middle_result_directory).exists():
        rmtree(args.middle_result_directory)


if __name__ == '__main__':
    cli_main()
