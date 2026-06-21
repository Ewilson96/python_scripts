from pathlib import Path
from tqdm import tqdm
import subprocess
import logging
import time

logger = logging.getLogger(__name__)

# def progbar(iterable, desc="progress"):
#     return tqdm(iterable, desc=desc)

def run_ansible_playbook(
    playbook_name: str,
    playbook_dir: str,
    inventory_file: str = None,
    ask_ssh_pass: bool = False,   #-k
    #become: bool = False,         #-b
    #ask_become_pass: bool = False #-K option 
    ) -> tuple[bool, str]: # "This function returns a tuple (ordered sequence) containing a boolean and a string."
    """
    Returns:
        tuple:
            success (bool)
            output (str)
    """
    playbook_path = Path(playbook_dir) / playbook_name
   # print(f"Running playbook: {playbook_path}")

    if not playbook_path.exists():
        raise FileNotFoundError(
            f"Playbook not found: {playbook_path}"
        )

    run_pb = ["ansible-playbook", str(playbook_path)] #list_01

    if inventory_file:
        #print(f"inventory found: {inventory_file}. Proceeding...")
        run_pb.extend(["-i", inventory_file]) #list_02 "ansible-playbook /home/ewilson/playbooks/patch.yml -i ../inventories/inventory.ini"
        if ask_ssh_pass:
            run_pb.append("-k")

        # if ask_become_pass:
        #     run_pb.append("-K")
        print('running...')
        print(      " ".join(run_pb))

    logger.info("run: %s", " ".join(run_pb)) # %s is a string placeholder for run_pb

    try:
        result = subprocess.run(
            run_pb,
            capture_output=False,
            text=True,
            check=False
        )

        #output = result.stdout + "\n" + result.stderr

        if result.returncode == 0:
            logger.info("Playbook completed successfully")
            return True

        logger.error("Playbook failed with rc=%s", result.returncode)
        return False

    except Exception as ew:
        logger.exception("Unexpected error running playbook")
        return False
    
if __name__ == "__main__":

    success = run_ansible_playbook(  #success/output
        playbook_name="test.yml", 
        playbook_dir="/home/ewilson/home_lab/ansible/playbooks",
        inventory_file="/home/ewilson/home_lab/ansible/inventories/inventory.ini",
        ask_ssh_pass=True,
        #ask_become_pass=True,
        #become=True
    )

    print(success)
