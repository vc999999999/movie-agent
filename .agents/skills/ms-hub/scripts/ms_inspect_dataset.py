# /// script
# dependencies = ["modelscope[datasets]>=1.35.0"]
# ///
"""
Deeply inspect the structure and content of a ModelScope dataset.

Usage:
    uv run scripts/ms_inspect_dataset.py --dataset_id "AI-ModelScope/alpaca-gpt4-data-zh" --operation full
    uv run scripts/ms_inspect_dataset.py --dataset_id "AI-ModelScope/alpaca-gpt4-data-zh" --operation overview
    uv run scripts/ms_inspect_dataset.py --dataset_id "AI-ModelScope/alpaca-gpt4-data-zh" --operation schema --split train
    uv run scripts/ms_inspect_dataset.py --dataset_id "AI-ModelScope/alpaca-gpt4-data-zh" --operation samples --num_samples 5
"""

import argparse


def format_size(size_bytes) -> str:
    if size_bytes is None:
        return 'unknown'
    try:
        size_bytes = int(size_bytes)
    except (TypeError, ValueError):
        return str(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'


def truncate_value(value, max_len: int = 200) -> str:
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + '...'
    return s


def inspect_overview(dataset_id: str, revision: str = 'master') -> str:
    from modelscope.hub.api import HubApi

    api = HubApi()
    output_lines = [f'=== Dataset: {dataset_id} ===\n']

    try:
        info = api.dataset_info(dataset_id, revision=revision)
        output_lines.append('--- Basic info ---')
        output_lines.append(f'  Name: {info.name}')
        if info.chinese_name:
            output_lines.append(f'  Chinese name: {info.chinese_name}')
        if info.description:
            output_lines.append(f'  Description: {truncate_value(info.description, 300)}')
        if info.tags:
            if isinstance(info.tags, list):
                if info.tags and isinstance(info.tags[0], dict):
                    tag_strs = [t.get('label', t.get('name', str(t))) for t in info.tags]
                else:
                    tag_strs = [str(t) for t in info.tags]
                output_lines.append(f'  Tags: {", ".join(tag_strs)}')
            elif isinstance(info.tags, dict):
                output_lines.append(f'  Tags: {info.tags.get("label", str(info.tags))}')
            else:
                output_lines.append(f'  Tags: {info.tags}')
        if info.license:
            output_lines.append(f'  License: {info.license}')
        output_lines.append(f'  Downloads: {info.downloads}')
        output_lines.append(f'  Likes: {info.likes}')
        output_lines.append(f'  Visibility: {"Public" if info.visibility == 5 else "Private"}')
        output_lines.append('')
    except Exception as e:
        output_lines.append(f'Failed to get basic info: {e}\n')

    try:
        files = api.get_dataset_files(
            repo_id=dataset_id, revision=revision, recursive=True
        )
        output_lines.append('--- File structure ---')
        if files:
            for f in files:
                name = f.get('Name', f.get('rfilename', 'unknown'))
                size = f.get('Size', f.get('size', None))
                size_str = f'({format_size(size)})' if size else ''
                output_lines.append(f'  {name}  {size_str}')
        else:
            output_lines.append('  (no files)')
        output_lines.append('')
    except Exception as e:
        output_lines.append(f'Failed to get file list: {e}\n')

    return '\n'.join(output_lines)


def inspect_schema(dataset_id: str, split: str = 'train',
                   revision: str = 'master') -> str:
    from modelscope.msdatasets import MsDataset

    output_lines = [f'=== Dataset Schema: {dataset_id} (split: {split}) ===\n']

    try:
        ds = MsDataset.load(dataset_id, split=split, trust_remote_code=True)

        output_lines.append('--- Column info ---')
        output_lines.append(f'  {"Column name":<30} {"Type"}')
        output_lines.append(f'  {"-"*30} {"-"*30}')
        for col_name, col_type in ds.features.items():
            output_lines.append(f'  {col_name:<30} {col_type}')

        output_lines.append(f'\n--- Statistics ---')
        output_lines.append(f'  Total rows: {len(ds):,}')
        output_lines.append(f'  Number of columns: {len(ds.column_names)}')
        output_lines.append(f'  Column names: {ds.column_names}')

    except Exception as e:
        output_lines.append(f'Failed to load dataset: {e}')
        output_lines.append('Hint: try specifying the correct split name, or check whether the dataset is accessible')

    return '\n'.join(output_lines)


def inspect_samples(dataset_id: str, split: str = 'train',
                    num_samples: int = 3, revision: str = 'master') -> str:
    from modelscope.msdatasets import MsDataset

    output_lines = [f'=== Dataset samples: {dataset_id} (split: {split}) ===\n']

    try:
        ds = MsDataset.load(dataset_id, split=split, trust_remote_code=True)

        actual_samples = min(num_samples, len(ds))
        output_lines.append(f'--- Sample preview (first {actual_samples} of {len(ds):,} total) ---')

        for i in range(actual_samples):
            sample = ds[i]
            output_lines.append(f'\n[{i + 1}]')
            for key, value in sample.items():
                output_lines.append(f'  {key}: {truncate_value(value, 200)}')

    except Exception as e:
        output_lines.append(f'Failed to load dataset: {e}')
        output_lines.append('Hint: try specifying the correct split name, or check whether the dataset is accessible')

    return '\n'.join(output_lines)


def inspect_full(dataset_id: str, split: str = 'train',
                 num_samples: int = 3, revision: str = 'master') -> str:
    parts = [
        inspect_overview(dataset_id, revision),
        inspect_schema(dataset_id, split, revision),
        inspect_samples(dataset_id, split, num_samples, revision),
    ]
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description='Deeply inspect a ModelScope dataset')
    parser.add_argument('--dataset_id', required=True,
                        help='Dataset ID (e.g. modelscope/alpaca-gpt4-data-zh)')
    parser.add_argument('--operation', default='full',
                        choices=['overview', 'schema', 'samples', 'full'],
                        help='Inspection type (default: full)')
    parser.add_argument('--split', default='train',
                        help='Dataset split (default: train)')
    parser.add_argument('--num_samples', type=int, default=3,
                        help='Number of samples to preview (default: 3)')
    parser.add_argument('--revision', default='master',
                        help='Revision (default: master)')

    args = parser.parse_args()

    ops = {
        'overview': lambda: inspect_overview(args.dataset_id, args.revision),
        'schema': lambda: inspect_schema(args.dataset_id, args.split, args.revision),
        'samples': lambda: inspect_samples(args.dataset_id, args.split,
                                           args.num_samples, args.revision),
        'full': lambda: inspect_full(args.dataset_id, args.split,
                                     args.num_samples, args.revision),
    }

    print(ops[args.operation]())


if __name__ == '__main__':
    main()
