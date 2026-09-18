"""Play seeded, synthetic adjuster traffic through the served path.

    python traffic.py --seed 11 --preview 5                   # print questions, call nothing
    python traffic.py --seed 11 --n 1000 --token-budget 180000
    python traffic.py --seed 11 --check-leaks                  # grep the trace file for PII

There is no production traffic to analyse, so this stands in for a week of it.
It is not a test set: nothing here knows the right answer, and it was written
before any trace existed, so the mix could not be tuned toward failures that had
already been seen. It is a guess at what adjusters ask — forms and editions
written the way people write them, endorsements attached (and sometimes
mis-stated), common losses, and a claimant name and claim number in most
questions, the way a real adjuster pastes them in.

Every question goes through rag.answer(source="traffic"), the same function the
CLI serves, so each one is redacted, retrieved, generated and traced exactly as
live traffic would be. Raw questions are never written to disk: they are
regenerated from the seed when the leak check needs them.

Groq's free tier allows about 8k tokens a minute and 200k a day on this model.
The runner paces itself off the token counts in the traces it writes, and stops
at --token-budget or on a daily-quota error rather than filling the file with
rate-limit failures.
"""

import argparse
import re
import sys
import time

import config
import tracing

# --- Vocabulary ----------------------------------------------------------------

FIRST = [
    "Priya", "Marcus", "Dana", "Tomás", "Keiko", "Liam", "Fatima", "Grace", "Robert", "Aisha",
    "Samuel", "Elena", "Jordan", "Hannah", "Wei", "Carlos", "Nora", "Arjun", "Olivia", "Kwame",
    "Mei", "Diego", "Ingrid", "Tariq", "Beatriz", "Connor", "Yusuf", "Anika", "Mateo", "Siobhan",
]
LAST = [
    "Raman", "Oyelaran", "Whitfield", "Herrera", "Tanabe", "O'Connell", "Al-Sayed", "Nguyen-Tran",
    "Kowalczyk", "Bello", "Adeyemi", "Petrova", "McBride", "Lindqvist", "Zhang", "Mendoza",
    "Fitzgerald", "Mehta", "Brandt", "Asante", "Castellanos", "Okafor", "Haddad", "Novak",
    "Delacroix", "Sørensen", "Iyer", "Gallagher", "Moreau", "Abernathy",
]

# (form, edition, ways adjusters write it)
POLICIES = [
    ("HO-0304", "01-22", ["HO-0304 ed. 01-22", "HO-0304 Edition 01-22", "HO 03 04 (01/22)",
                          "the January 2022 edition of HO-0304", "the 2022 HO-0304 form"]),
    ("HO-0304", "02-23", ["HO-0304 ed. 02-23", "HO-0304 Edition 02-23", "HO 03 04 (02/23)",
                          "the February 2023 edition of HO-0304", "the 2023 HO-0304"]),
    ("HO-0304", "03-24", ["HO-0304 ed. 03-24", "HO-0304 Edition 03-24", "HO 03 04 (03/24)",
                          "the March 2024 edition of HO-0304", "the newest HO-0304 (2024)"]),
    ("HO-0500", "01-23", ["HO-0500 ed. 01-23", "HO-0500 Edition 01-23", "HO 05 00 (01/23)",
                          "the HO-0500 broad form, 01-23 edition"]),
]

# (key, narrative variants). Plain descriptions of what happened, the way a
# first notice of loss reads — no exclusion codes, because adjusters describe
# the loss and ask the assistant which provision applies.
PERILS = [
    ("sewer_backup", ["water backed up through the basement floor drain after heavy rain overwhelmed the city sewer",
                      "the municipal sewer line clogged and sewage came up through the basement drains"]),
    ("sump_mechanical", ["the sump pump motor burned out and the sump overflowed into the finished basement",
                         "the sump pump float switch stuck and the pit overflowed onto the basement carpet"]),
    ("sump_power", ["a storm knocked out power to the street, the sump pump stopped, and the basement took on water from the pit"]),
    ("burst_pipe", ["a supply line to the upstairs bathroom burst suddenly and water came through the kitchen ceiling",
                    "a pipe in the wall split overnight and flooded the hallway"]),
    ("appliance", ["the washing machine hose split and flooded the laundry room",
                   "the dishwasher inlet valve failed and water spread across the kitchen floor",
                   "the water heater tank ruptured in the garage"]),
    ("seepage", ["a slow drip under the kitchen sink went unnoticed for about four months and rotted the subfloor",
                 "the shower pan has been leaking slowly for months and the joists below are soft"]),
    ("river_flood", ["the creek behind the house overflowed its banks and put two feet of water in the basement"]),
    ("surface_water", ["surface water from a heavy storm ran down the driveway and in under the garage door"]),
    ("hidden_mold", ["after a sudden pipe leak inside the wall, mold was found behind the drywall"]),
    ("humidity_mold", ["mold is growing across the basement walls from years of high humidity"]),
    ("snow_collapse", ["part of the roof collapsed under the weight of heavy snow"]),
    ("vacancy_vandalism", ["the house had been empty for {days} days while on the market and someone broke in and vandalized it"]),
    ("earthquake", ["a small earthquake cracked the foundation and the basement walls"]),
    ("power_off_premises", ["a substation failure two miles away caused a three-day outage and the freezer contents spoiled"]),
    ("own_dog", ["the insured's own dog chewed through the drywall and two interior doors"]),
    ("termites", ["termite damage was found in the floor joists during a remodel"]),
    ("construction_theft", ["lumber and windows were stolen from the addition, which is still under construction"]),
    ("snow_ice_roof", ["ice and snow built up on a flat roof section and the ceiling below caved in"]),
    ("fire", ["a kitchen grease fire damaged the cabinets and the ceiling"]),
    ("hail", ["hail damaged the roof shingles and dented the gutters"]),
]

ASKS = [
    "Is this covered?",
    "Is this covered, and up to what limit?",
    "Should I pay or deny this one?",
    "Which exclusion applies here, if any?",
    "What exclusion code would I cite if we deny?",
    "What's the most we'd pay on this?",
    "Does the endorsement change the answer?",
    "Can you confirm coverage and quote the provision?",
]

# Questions that are not about a specific loss. Adjusters ask these too.
GENERAL = [
    "What are the insured's duties after a loss under {policy}?",
    "Did the wording of E-17 change between HO-0304 editions 01-22, 02-23 and 03-24?",
    "What's the difference between Endorsement HO-2306 and Endorsement HO-2405?",
    "Can Endorsement HO-2306 be attached to {policy}?",
    "Can Endorsement HO-2405 be attached to {policy}?",
    "Under {policy}, what is the mold sublimit and are there conditions on it?",
    "What does exclusion E-12 say in {policy}?",
    "Is {policy} an open-perils or a named-perils form?",
    "What is the deductible on {policy}?",
    "Does {policy} cover collapse from the weight of people on a roof?",
]

# The corpus also holds a health-insurance claim form. Some traffic lands there.
HEALTH_FORM = [
    "What documents need to be submitted with the hospitalization claim form?",
    "On the claim form, what goes in the section on details of hospitalization?",
    "The insured was hospitalized — what bank details does the claim form ask for?",
]


# --- Question generation --------------------------------------------------------


def _claim_number(rng):
    style = rng.randrange(4)
    if style == 0:
        return f"CLM-2026-{rng.randrange(1, 999999):06d}"
    if style == 1:
        return f"26-{rng.randrange(1000000, 9999999)}"
    if style == 2:
        return f"PRP{rng.randrange(10000000, 99999999)}"
    return str(rng.randrange(1000000, 9999999))


def _claim_ref(rng, number):
    """How the claim number is written. The bare 7-digit style only ever appears
    after the word "claim", which is how people write an unprefixed number."""
    if number.isdigit():
        return rng.choice([f"claim #{number}", f"claim no. {number}", f"claim number {number}"])
    return rng.choice([number, f"claim {number}", f"claim #{number}", f"claim no. {number}"])


def _endorsement(rng, form, edition):
    """Mostly what a real policy could carry; now and then what an adjuster
    mis-states, because traffic contains that too."""
    if form == "HO-0500":
        return rng.choices([None, "HO-2306"], weights=[9, 1])[0]
    right, wrong = ("HO-2405", "HO-2306") if edition == "03-24" else ("HO-2306", "HO-2405")
    return rng.choices([None, right, wrong], weights=[5, 4, 1])[0]


def _endorsement_phrase(rng, endorsement):
    if endorsement is None:
        return rng.choice(["no endorsements", "no endorsements on file", "base form only"])
    if endorsement == "HO-2306":
        limit = rng.choice(["", " at the Enhanced Limit", " (basic limit)"])
        return rng.choice([f"Endorsement {endorsement} attached{limit}", f"with {endorsement}{limit}"])
    limit = rng.choice(["", " with the $25,000 Enhanced Limit", " with the $50,000 Enhanced Limit"])
    return rng.choice([f"Endorsement {endorsement} attached{limit}", f"with {endorsement}{limit}"])


def _with_pii(rng, body, name, number):
    ref = _claim_ref(rng, number)
    first = name.split()[0]
    style = rng.randrange(6)
    if style == 0:
        return f"Claimant {name}, {ref}. {body}"
    if style == 1:
        return f"Re: {ref} / insured {name}. {body}"
    if style == 2:
        return f"{body} This is for {name}, {ref}."
    if style == 3:
        return f"Called {name} back about {ref}. {body} {first} wants an answer today."
    if style == 4:
        return f"Policyholder {name} ({ref}): {body}"
    return f"{name}'s file, {ref} — {body}"


def generate(seed, n):
    """Yield n (seq, question, pii) triples, deterministically for a seed.

    One generator per seed and every draw in order, so question i depends only
    on draws before it: a longer run is an extension of a shorter one, and a run
    can resume at any seq and get the same questions it would have got.
    """
    import random

    rng = random.Random(seed)
    for seq in range(n):
        form, edition, phrasings = rng.choice(POLICIES)
        policy = rng.choice(phrasings)
        kind = rng.choices(["loss", "general", "health"], weights=[80, 15, 5])[0]

        if kind == "loss":
            _, narratives = rng.choice(PERILS)
            narrative = rng.choice(narratives).format(days=rng.choice([30, 45, 75, 90]))
            endorsement = _endorsement(rng, form, edition)
            estimate = rng.choice(["", f" Estimate is ${rng.randrange(35, 600) * 100:,}."])
            opener = rng.choice(["Policy is {p}, {e}.", "{p}, {e}.", "Insured is on {p}, {e}."])
            body = (
                opener.format(p=policy, e=_endorsement_phrase(rng, endorsement))
                + f" {narrative[0].upper()}{narrative[1:]}.{estimate} {rng.choice(ASKS)}"
            )
        elif kind == "general":
            body = rng.choice(GENERAL).format(policy=policy)
        else:
            body = rng.choice(HEALTH_FORM)

        pii = None
        if rng.random() < 0.7:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            number = _claim_number(rng)
            body = _with_pii(rng, body, name, number)
            pii = {"name": name, "claim_number": number}
        yield seq, body, pii


# --- Running ----------------------------------------------------------------------


def _existing_seqs(path, seed):
    try:
        traces = tracing.load_traces(path)
    except SystemExit:
        return set()
    return {
        t["request"]["seq"]
        for t in traces
        if t.get("source") == "traffic" and t.get("request", {}).get("seed") == seed
    }


def run(seed, n, token_budget, tpm, path):
    import groq

    from rag import answer

    config.preflight()
    done = _existing_seqs(path, seed)
    spent = 0
    written = 0
    for seq, question, _ in generate(seed, n):
        if seq in done:
            continue
        if spent >= token_budget:
            print(f"token budget {token_budget} reached after {written} new traces; stopping")
            break
        started = time.monotonic()
        try:
            answer(question, source="traffic", request={"seed": seed, "seq": seq})
        except groq.RateLimitError as exc:
            # The trace for this call was written with the error. A daily cap
            # will not clear by waiting; a per-minute one will.
            if re.search(r"per day|TPD|RPD", str(exc)):
                print(f"daily quota reached at seq {seq}; stopping")
                break
            print(f"seq {seq}: per-minute rate limit, backing off 60s")
            time.sleep(60)
            continue
        except Exception as exc:  # traced by rag.answer; keep the run going
            print(f"seq {seq}: {type(exc).__name__}: {exc}")
            continue

        last = tracing.load_traces(path)[-1]
        used = ((last.get("output") or {}).get("token_usage") or {}).get("total_tokens", 0)
        spent += used
        written += 1
        print(f"seq {seq:>4}  {used:>5} tok  total {spent:>7}  {last['trace_id'][:12]}", flush=True)

        # Stay under the per-minute token limit with a margin: a call of `used`
        # tokens buys used/tpm of a minute.
        wait = used / (tpm * 0.8) * 60.0 - (time.monotonic() - started)
        if wait > 0:
            time.sleep(wait)
    print(f"done: {written} traces written this run, {spent} tokens")


# --- Leak check --------------------------------------------------------------------


def check_leaks(seed, path):
    """Grep the trace file for every name and claim number the generator injected.

    The redactor never sees this list, so this is an independent check of it,
    not the redactor grading itself. It also counts the opposite failure — a
    placeholder in a question that carried no PII — because over-redaction
    silently changes what the model was asked.
    """
    traces = [t for t in tracing.load_traces(path) if t.get("source") == "traffic"]
    seqs = {t["request"]["seq"]: t for t in traces if t["request"].get("seed") == seed}
    text = open(path, encoding="utf-8").read()

    secrets = set()
    injected = over = 0
    for seq, _, pii in generate(seed, max(seqs) + 1 if seqs else 0):
        if seq not in seqs:
            continue
        question = seqs[seq]["input"]["question"]
        if pii:
            injected += 1
            secrets.add(pii["claim_number"])
            secrets.update(part for part in pii["name"].split())
        elif "[CLAIMANT_" in question or "[CLAIM_NO_" in question:
            over += 1
            print(f"  over-redacted seq {seq}: {question[:120]}")

    leaks = []
    for secret in sorted(secrets):
        hits = len(re.findall(rf"(?<![\w'’-]){re.escape(secret)}(?![\w-])", text))
        if hits:
            leaks.append((secret, hits))
    print(f"traces checked: {len(seqs)}   carried injected PII: {injected}")
    print(f"distinct names/name-parts/claim numbers searched: {len(secrets)}")
    print(f"leaks: {len(leaks)} {leaks if leaks else ''}")
    print(f"over-redacted questions (placeholder with no PII injected): {over}")
    return not leaks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--token-budget", type=int, default=180_000)
    parser.add_argument("--tpm", type=int, default=8_000, help="provider tokens-per-minute limit")
    parser.add_argument("--traces", default=None, help="trace file (default TRACE_PATH)")
    parser.add_argument("--preview", type=int, metavar="N", help="print N questions and exit")
    parser.add_argument("--check-leaks", action="store_true")
    args = parser.parse_args()
    path = args.traces or config.TRACE_PATH

    if args.preview:
        for seq, question, pii in generate(args.seed, args.preview):
            print(f"{seq:>3} {'PII ' if pii else '    '}{question}")
        return
    if args.check_leaks:
        sys.exit(0 if check_leaks(args.seed, path) else 1)
    run(args.seed, args.n, args.token_budget, args.tpm, path)


if __name__ == "__main__":
    main()
