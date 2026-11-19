import subprocess


def announce(name: str) -> None:
    """Print a greeting through the system's echo."""
    subprocess.run(f"echo Hello, {name}!", shell=True, check=True)
