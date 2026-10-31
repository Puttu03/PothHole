"""Create an isolated environment and install dependencies. Python 3.11 recommended."""
import pathlib, subprocess, sys, venv
root=pathlib.Path(__file__).resolve().parent
venv.create(root/'.venv',with_pip=True)
python=root/'.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
def pip(*args): subprocess.run([str(python),'-m','pip',*args],check=True)
pip('install','--upgrade','pip')
if sys.platform=='win32':
 pip('install','torch==2.8.0','torchvision==0.23.0','--index-url','https://download.pytorch.org/whl/cu126')
pip('install','-r',str(root/'requirements.txt'))
print('Setup complete. Run: python run.py. Install Ollama separately from https://ollama.com')
