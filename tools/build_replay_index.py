"""Build the self-contained, event-only replay reader (requires .NET 10 SDK)."""
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['dotnet', 'publish', str(root/'native/replay_index/DollyReplayIndex.csproj'),
                    '-c', 'Release', '-o', str(root/'native/bin/win64'),
                    '--nologo', '-v', 'quiet', '-p:RestoreLockedMode=true'], cwd=root, check=True)


if __name__ == '__main__':
    main()
