import requests
import hashlib
from app.config import DISABLE_PWNEDPASSWORDS


def check_pwnedpasswords(password, bypass=False):
    """
    Checks a password against Pwned Passwords using the k-anonymity range endpoint

    Returns the amount of matches if the password is in Pwned Passwords, false otherwise.
    """
    if not bypass and DISABLE_PWNEDPASSWORDS:
        return False
    else:
        sha1_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        lookup_hash = sha1_hash[0:5]
        pwnedpasswords_res = requests.get(
            "https://api.pwnedpasswords.com/range/" + lookup_hash,
            headers={"Add-Padding": "true"},
        ).content.decode("utf-8")
        unpad_matches = list(
            filter(lambda x: int(x.split(":")[1]) > 0, pwnedpasswords_res.splitlines())
        )

        found = list(filter(lambda x: sha1_hash[5:] == x.split(":")[0], unpad_matches))
        if len(found) > 0:
            return found[0].split(":")[1]
        else:
            return False