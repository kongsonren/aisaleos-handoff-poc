"""Local subprocess regressions; no network, credentials or deployment."""
import pathlib
import subprocess
import sys

p = subprocess.run([sys.executable, '-m', 'unittest', 'test_security.Security',
                    'test_daemon.Tests', '-v'], capture_output=True)
pathlib.Path('green.log').write_bytes(p.stdout + p.stderr)
print('Python:',sys.version)
print('regression exit:',p.returncode)
sys.exit(p.returncode)
