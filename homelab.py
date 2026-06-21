from pathlib import Path
from tqdm import tqdm
import subprocess
import logging
import time

logger = logging.getLogger(__name__)


def progbar(iterable, desc="progress"):
    return tqdm(iterable, desc=desc)

def run_ansible_playbook(
    playbook_name: str,
    playbook_dir: str,
    inventory_file: str = None,
    #ask_pass: bool = False,
    become: bool = False,
    ask_pass: bool = False  #K option 
    ) -> tuple[bool, str]: # "This function returns a tuple (ordered sequence) containing a boolean and a string."
    """
    Returns:
        tuple:
            success (bool)
            output (str)
    """
    playbook_path = Path(playbook_dir) / playbook_name

    if not playbook_path.exists():
        raise FileNotFoundError(
            f"Playbook not found: {playbook_path}"
        )

    run_pb = ["ansible-playbook", str(playbook_path)] #list_01

    if inventory_file:
        run_pb.extend(["-i", inventory_file]) #list_02 "ansible-playbook /home/ewilson/playbooks/patch.yml -i ../inventories/inventory.ini"

    logger.info("run: %s", " ".join(run_pb)) # %s is a string placeholder for run_pb

    try:
        result = subprocess.run(
            run_pb,
            capture_output=True,
            text=True,
            check=False
        )

        output = result.stdout + "\n" + result.stderr

        if result.returncode == 0:
            logger.info("Playbook completed successfully")
            return True, output

        logger.error("Playbook failed with rc=%s", result.returncode)
        return False, output

    except Exception as fail:
        logger.exception("Unexpected error running playbook")
        return False, str(fail)
    
if __name__ == "__main__":

    #tqdm stuff
    pb = ["test.yml"]
    for i in progbar(pb):
        x,y = run_ansible_playbook(  #success/output
        playbook_name="test.yml", 
        playbook_dir="/home/ewilson/home_lab/ansible/playbooks",
        inventory_file="/home/ewilson/home_lab/ansible/inventories/inventory.ini",
        become=True
    )

    print(y)
