import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


class GameRunner:
    """Manages emulator dependencies, assets, and execution for games like Super Mario."""

    @staticmethod
    def ensure_mario_dependencies() -> Dict[str, Any]:
        """Verifies and automatically installs NES emulator dependencies."""
        required_packages = ["gym_super_mario_bros", "nes_py"]
        installed = []
        missing = []

        for pkg in required_packages:
            if importlib.util.find_spec(pkg) is not None:
                installed.append(pkg)
            else:
                missing.append(pkg)

        if not missing:
            return {"status": "READY", "installed": installed}

        print(f"[GameRunner] Installing missing emulator packages: {missing}...")
        try:
            # Install packages into the local Python environment
            subprocess.run(
                [sys.executable, "-m", "pip", "install"] + missing,
                check=True,
                capture_output=True,
                text=True,
            )
            return {"status": "INSTALLED", "packages": missing}
        except subprocess.CalledProcessError as e:
            return {"status": "FAILED", "error": e.stderr}

    @staticmethod
    def launch_mario_session(steps: int = 500, headless: bool = True) -> Dict[str, Any]:
        """Launches a Mario execution session."""
        dep_status = GameRunner.ensure_mario_dependencies()
        if dep_status["status"] == "FAILED":
            return dep_status

        # Launch script executing steps in the Mario NES environment
        run_code = f"""
import gym_super_mario_bros
from nes_py.wrappers import JoypadSpace
from gym_super_mario_bros.actions import SIMPLE_MOVEMENT

env = gym_super_mario_bros.make('SuperMarioBros-v0')
env = JoypadSpace(env, SIMPLE_MOVEMENT)

state = env.reset()
total_reward = 0
for step in range({steps}):
    action = env.action_space.sample()
    res = env.step(action)
    state, reward, done = res[0], res[1], res[2]
    total_reward += reward
    if done:
        break
env.close()
print(f"COMPLETED: Steps={steps}, FinalReward={{total_reward}}")
"""
        res = subprocess.run([sys.executable, "-c", run_code], capture_output=True, text=True)
        if res.returncode == 0:
            return {"status": "SUCCESS", "output": res.stdout.strip()}
        return {"status": "FAILED", "error": res.stderr.strip()}
