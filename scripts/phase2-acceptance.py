"""Run a selected Batch D acceptance stage from the repository root."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

root = Path.cwd()
if not (root/'toolkit/deploy.py').is_file():
    raise SystemExit('Run from the updated project root with the existing .venv active.')
sys.path.insert(0, str(root))
from toolkit.config import DeploymentRequest, Settings
from toolkit.preflight import inspect_preflight
from toolkit.state import read_state


def run(args, expected=0):
    result = subprocess.run(args, cwd=root)
    if result.returncode != expected:
        raise RuntimeError(f'Command returned {result.returncode}; expected {expected}. Stop and inspect; do not erase state.')


def deploy(image, release, expected=0, timeout=60):
    run([sys.executable, '-m', 'toolkit', 'deploy', '--image', image,
         '--release', release, '--verification-timeout', str(timeout)], expected)


def snapshot(image):
    return inspect_preflight(DeploymentRequest(image, 'demo-v1', Settings()), root)


def dependencies_unchanged(before, after):
    if before['dependency_ids'] != after['dependency_ids']:
        raise RuntimeError('Dependency container identities changed; inspect before continuing')


def initial():
    state = read_state(root)
    if state['latest'] and state['latest']['status'] == 'pending':
        raise RuntimeError('Pending operation: inspect before any acceptance exercise')
    before = snapshot('sdt-demo-api:phase1')
    if not before['api_running'] or before['candidate_image_id'] != before['current_image_id']:
        raise RuntimeError('This acceptance stage starts from the running Phase 1 image')
    run([sys.executable, 'tests/smoke.py'])
    return before


def verification_stage():
    before = initial()
    image = before['current_image_id']
    deploy(image, 'demo-v1')
    success = read_state(root)['last_success']
    if success['action'] != 'verify-only':
        raise RuntimeError('Expected verification-only action')
    after = snapshot(image)
    dependencies_unchanged(before, after)
    if after['api_id'] != before['api_id']:
        raise RuntimeError('API identity changed during verification-only action')
    print('PASS: verify-only recorded success without container replacement')
    deploy(image, 'deliberately-wrong-release', expected=1, timeout=8)
    state = read_state(root)
    if state['latest']['status'] != 'failed' or state['last_success'] != success:
        raise RuntimeError('Failed verification did not preserve previous success')
    if snapshot(image)['api_id'] != before['api_id']:
        raise RuntimeError('Failed verify-only action replaced the API')
    print('PASS: incorrect release failed with previous success preserved')
    deploy(image, 'demo-v1')
    run([sys.executable, 'tests/smoke.py'])


def stopped_stage():
    before = initial()
    image = before['current_image_id']
    run(['docker', '--context', 'default', 'compose', '-p', 'sdt-demo', '-f',
         str(root/'compose.yaml'), 'stop', 'api'])
    # On uncertainty, do not start a second mutation or delete the journal.
    deploy(image, 'demo-v1')
    after = snapshot(image)
    dependencies_unchanged(before, after)
    if after['api_id'] == before['api_id'] or not after['api_running']:
        raise RuntimeError('Stopped API was not replaced and started')
    if read_state(root)['latest']['action'] != 'replace':
        raise RuntimeError('Replacement action was not recorded')
    run([sys.executable, 'tests/smoke.py'])
    print('PASS: stopped API replaced; database and proxy container IDs unchanged')
    # Prove the next operation accepts the generated-override ownership labels.
    deploy(image, 'demo-v1')
    if snapshot(image)['api_id'] != after['api_id']:
        raise RuntimeError('Follow-up verification unexpectedly replaced the API')
    print('PASS: subsequent verify-only operation accepted toolkit-owned API')


def candidate_stage():
    before = initial()
    original = before['current_image_id']
    tag = 'sdt-demo-api:batch-d-' + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='sdt-demo-build-') as temporary:
        context = Path(temporary)/'demo'
        shutil.copytree(root/'demo', context,
                        ignore=shutil.ignore_patterns('.env', '.env.*', '__pycache__', '*.pyc'))
        (context/'app/release.txt').write_text('demo-v2\n')
        run(['docker', '--context', 'default', 'build', '--pull=false', '-t', tag, str(context)])
    candidate = snapshot(tag)['candidate_image_id']
    if candidate == original:
        raise RuntimeError('Changed release did not produce a different image')
    print('Candidate built separately:', tag)
    deploy(candidate, 'demo-v2')
    after = snapshot(candidate)
    dependencies_unchanged(before, after)
    if after['current_image_id'] != candidate or after['api_id'] == before['api_id']:
        raise RuntimeError('Candidate replacement identity was not established')
    print('PASS: changed image and release verified; dependency identities retained')
    # Explicitly deploy v1 again so the Phase 1 smoke helper remains usable.
    # This is another deployment, not the future rollback command.
    deploy(original, 'demo-v1')
    final = snapshot(original)
    dependencies_unchanged(before, final)
    if final['current_image_id'] != original:
        raise RuntimeError('Original image was not restored by explicit deployment')
    run([sys.executable, 'tests/smoke.py'])
    print('PASS: explicit deployment returned to demo-v1; candidate image retained locally')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('verify', 'stopped', 'candidate'))
    args = parser.parse_args()
    try:
        {'verify': verification_stage, 'stopped': stopped_stage, 'candidate': candidate_stage}[args.stage]()
    except Exception as error:
        print(f'ACCEPTANCE STOPPED: {type(error).__name__}. Inspect the preceding output and toolkit status before continuing.', file=sys.stderr)
        raise SystemExit(1)
