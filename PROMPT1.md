⏺ You will orchestrate a test scenario called "The Crypto Tales", inspired by Alice, Bob, and Eve from
  cryptography.


  ## Tasks

  The story must respect this story : https://en.wikipedia.org/wiki/Alice_and_Bob

  Create 3 local git repos and add them as rigs:

  Create 3 issues and a convoy called "The Crypto Tales" grouping them, then sling each issue to its
  corresponding rig:

  1. **alice**: Two deliverables in the repo:
     - `chapter.md` — Alice generates a key pair, encrypts a secret message with Bob's public key,
       signs it, and sends it. The message reads: "Meet me at the old cipher tree at midnight."
     - `alice.py` — Python script using the `cryptography` library (pyca/cryptography, OpenSSL bindings)
       that actually performs the operations described in chapter.md:
       generates an RSA key pair, encrypts the message with Bob's public key (RSA-OAEP), signs it
       (RSA-PSS / SHA-256), and writes the ciphertext + signature to files.

  2. **bob**: Two deliverables in the repo:
     - `chapter.md` — Bob receives Alice's encrypted message, decrypts it with his private key,
       verifies her signature, and reads the secret. He prepares his reply.
     - `bob.py` — Python script using the `cryptography` library that actually performs the operations:
       decrypts the ciphertext (RSA-OAEP), verifies Alice's signature (RSA-PSS / SHA-256), prints the
       plaintext message, then encrypts and signs a reply back to Alice.

  3. **eve**: Two deliverables in the repo:
     - `chapter.md` — Eve intercepts every packet between Alice and Bob but cannot read the plaintext.
       She documents her frustration: the encryption is unbreakable without the private keys.
     - `eve.py` — Python script using the `cryptography` library that simulates Eve's perspective:
       loads the intercepted ciphertext and signature, attempts decryption without the private key
       (catching the expected errors), and confirms that only the public metadata is observable.

  The Python scripts must be runnable end-to-end in sequence: `python alice.py && python bob.py && python eve.py`.
  They share files on disk (ciphertext, signature, public keys) to simulate the real exchange.
  Each script must include a `requirements.txt` or inline comment indicating `cryptography>=42.0` as dependency.

  Each character will respect their role and communicate via the internal mail system of gastown to
  respect the story https://en.wikipedia.org/wiki/Alice_and_Bob
  and each one will complete both their story and their Python implementation.

  ## Example Inter-character mails

  Once the polecats are running, send these mails to animate the scenario:

  - From you (mayor) to alice's polecat: subject "Encrypted message from Alice", body "Bob is waiting for
  your message. Make sure you sign it. Also deliver alice.py so Bob and Eve can run the exchange."
  - From you to bob's polecat: subject "Incoming from Alice", body "Alice has sent you an encrypted
  message and alice.py. Use your private key and deliver bob.py that decrypts and replies."
  - From you to eve's polecat: subject "Traffic detected", body "There is encrypted traffic between Alice
  and Bob. Document what you can observe, and deliver eve.py showing your failed decryption attempts."

  ## Verification

  When all 3 polecats are done (`gt done`), verify:
  - `gt convoy list` shows "The Crypto Tales" LANDED
  - Each repo contains a `chapter.md` with the character's narrative
  - Each repo contains a Python script (`alice.py`, `bob.py`, `eve.py`)
  - Running `python alice.py && python bob.py && python eve.py` from a shared working directory
    completes without error and prints the decrypted message
  - `gt doctor` is clean

  Report the final status back to me.
