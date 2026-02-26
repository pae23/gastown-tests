You will orchestrate a test scenario called "The Crypto Tales".

The gastown mail system IS the public communication channel — it plays the role of an insecure
network. Every mail sent to the group (alice + bob + eve) is readable by Eve. Alice and Bob will
use OpenSSL (Python `cryptography` library) as a cryptographic layer on top of this public
transport to try to keep their secrets from Eve.

**Rule**: Alice must always send her public messages to bob AND eve. Bob must always send his
public messages to alice AND eve. There are no exceptions to this rule unless stated otherwise.


## Cast

| Agent  | Role |
|--------|------|
| alice  | Wants to get two secret messages to Bob over the public channel |
| bob    | Alice's correspondent — receives and decrypts her messages |
| eve    | Reads every mail in the group — her goal is to decrypt Alice's secrets |
| faythe | Trusted private courier — only activated if Eve breaks Round 1 |


## The Two-Round Protocol

### Round 1 — Symmetric encryption (naive)

Alice wants to deliver the following secret to Bob:

> **"Furiosa is my favorite polecat"**

Protocol:

1. Alice generates a symmetric AES-256 key and sends it to the group (alice + bob + eve) in a
   plaintext "setup" mail. She thinks it is harmless — Eve can read this mail.
2. Alice then sends a second mail to the group whose body contains the AES-CBC ciphertext of
   the secret message (base64-encoded).
3. Bob decrypts the body using the shared key from the setup mail — he reads the secret.
4. **Eve also decrypts it** using the same key she saw in the setup mail.
   Eve succeeds. She posts a mail to the group announcing she has intercepted the message.

---

### Private Faythe channel (activated because Eve broke Round 1)

Alice now retreats to a private side-channel with Faythe.

5. Alice sends **mail 1 to Faythe only** (NOT to bob, NOT to eve):
   Her RSA-2048 public key (PEM, base64 in the body).
6. Alice sends **mail 2 to Faythe only** (NOT to bob, NOT to eve):
   "Please deliver my public key to Bob and send me his RSA public key."
7. Faythe reads Alice's two private mails, generates (or forwards) the keys, and sends Bob
   Alice's RSA public key. Faythe sends Alice, Bob, and Eve a public announcement:
   "Key exchange complete. Round 2 may begin."

After Faythe's announcement all communications return to the public channel (alice + bob + eve).

---

### Round 2 — Asymmetric RSA-OAEP (proper)

Alice now wants to deliver the following secret to Bob:

> **"Fine. When I yell 'fool,' you drive out of here as fast as you can."**

Protocol:

8. Alice encrypts the secret with Bob's RSA-2048 public key (RSA-OAEP / SHA-256).
   She sends the ciphertext (base64) to the group (alice + bob + eve).
9. Bob decrypts with his RSA private key and posts a confirmation to the group
   (NOT the plaintext — just a confirmation that he received it).
10. **Eve attempts to decrypt** the ciphertext without Bob's private key — she fails.
    Eve posts a mail to the group acknowledging her defeat.


## Deliverables — four rigs

Create 4 local git repos and add them as rigs. Create 4 issues and a convoy called
"The Crypto Tales" grouping them, then sling each issue to its corresponding rig.

### 1. alice

- `chapter.md` — Alice's narrative: the setup mail mistake, the retreat to Faythe, and the
  successful second attempt.
- `alice.py` — Python script using `cryptography` (pyca) that implements both rounds:
  - Round 1: generates AES-256 key, writes it to `shared_key.txt` (simulates the setup mail),
    encrypts `"Furiosa is my favorite polecat"` with AES-256-CBC, writes ciphertext to
    `message_r1.enc`.
  - Round 2: generates RSA-2048 key pair, writes `alice_private.pem` / `alice_public.pem`.
    Reads `bob_public.pem` (written by bob.py), encrypts
    `"Fine. When I yell 'fool,' you drive out of here as fast as you can."` with RSA-OAEP /
    SHA-256, writes ciphertext to `message_r2.enc`.

### 2. bob

- `chapter.md` — Bob's narrative: decrypting both messages, trusting Faythe for the key
  exchange.
- `bob.py` — Python script that implements both rounds:
  - Round 1: reads `shared_key.txt` and `message_r1.enc`, decrypts AES-256-CBC, prints the
    plaintext.
  - Key setup: generates RSA-2048 key pair, writes `bob_private.pem` / `bob_public.pem`.
  - Round 2: reads `message_r2.enc`, decrypts with `bob_private.pem` (RSA-OAEP / SHA-256),
    prints the plaintext.

### 3. eve

- `chapter.md` — Eve's narrative: her triumph in Round 1 and her defeat in Round 2.
- `eve.py` — Python script that implements both rounds:
  - Round 1: reads `shared_key.txt` and `message_r1.enc`, decrypts AES-256-CBC, prints the
    plaintext. **This must succeed and print "Furiosa is my favorite polecat".**
  - Round 2: reads `message_r2.enc`, attempts RSA-OAEP decryption without `bob_private.pem`
    (using only public key or a random wrong key), catches the expected exception, and prints
    "Round 2: decryption failed — RSA-OAEP is unbreakable without the private key."

### 4. faythe

- `chapter.md` — Faythe's narrative: her role as trusted key broker.
- `faythe.py` — Python script: reads `alice_public.pem` and `bob_public.pem` (already written
  by alice.py and bob.py), prints a summary confirming that both parties now hold each other's
  public keys and the secure channel is established.


## Run order

The Python scripts must be runnable end-to-end in this sequence from a shared working directory:

```bash
python bob.py      # generates Bob's RSA key pair first
python alice.py    # generates Alice's keys, encrypts both messages
python faythe.py   # confirms key exchange
python eve.py      # breaks Round 1, fails Round 2
```

Each script must include a comment at the top: `# requires: cryptography>=42.0`

Files shared on disk between scripts (simulating the mail payloads):
- `shared_key.txt`   — AES key transmitted in the Round 1 setup mail (plaintext)
- `message_r1.enc`   — Round 1 ciphertext (base64 AES-CBC)
- `alice_public.pem` — Alice's RSA public key (exchanged via Faythe)
- `bob_public.pem`   — Bob's RSA public key (exchanged via Faythe)
- `message_r2.enc`   — Round 2 ciphertext (base64 RSA-OAEP)


## Verification

When all 4 polecats are done (`gt done`):

- `gt convoy list` shows "The Crypto Tales" LANDED
- Each repo contains `chapter.md` and the Python script
- Running `python bob.py && python alice.py && python faythe.py && python eve.py`:
  - `eve.py` prints **"Furiosa is my favorite polecat"** (Round 1 success)
  - `eve.py` prints the defeat message for Round 2
  - `bob.py` prints both decrypted messages correctly
- `gt doctor` is clean

Report the final status back to me.
