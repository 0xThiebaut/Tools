from argparse import ArgumentParser
from email.generator import Generator
from email.headerregistry import Address
from email.message import EmailMessage
from email.parser import HeaderParser
from email.policy import default
from fileinput import input
from math import log10
from os import environ
from os.path import join
from random import choice
from re import search, MULTILINE, DOTALL
from sys import stderr
from typing import Iterable

try:
    from openai import Completion
except ModuleNotFoundError:
    print(
        "Did you install the openai module? See https://pypi.org/project/openai/",
        file=stderr,
    )
    raise


def quote(message: str) -> str:
    return "\n".join([f"> {line}" for line in message.split("\n")])


class Completer(object):
    def __init__(
        self,
        api_key: str,
        api_base: str,
        api_type: str = "azure",
        api_version: str = "2022-12-01",
        engine: str = "text-davinci-003",
        temperature: float = 0.6,
        max_tokens: int = 250,
        top_p: int = 1,
        frequency_penalty: int = 2,
        presence_penalty: int = 1,
        best_of: int = 1,
        stop=None,
    ):
        self.api_key = api_key
        self.api_base = api_base
        self.api_type = api_type
        self.api_version = api_version
        self.engine = engine
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.best_of = best_of
        self.stop = stop

    def complete(self, prompt):
        result = Completion.create(
            prompt=prompt,
            api_key=self.api_key,
            api_base=self.api_base,
            api_type=self.api_type,
            api_version=self.api_version,
            engine=self.engine,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            presence_penalty=self.presence_penalty,
            best_of=self.best_of,
            stop=self.stop,
        )

        assert "choices" in result
        assert len(result["choices"]) >= 1
        assert "text" in result["choices"][0]

        completion = result["choices"][0]["text"].strip()
        return completion


class Correspondent(object):
    def __init__(self, address: Address, completer: Completer):
        self.address = address
        self.completer = completer

    @property
    def ref(self) -> str:
        return str(self.address)

    def __str__(self):
        return self.ref

    def __eq__(self, other):
        return isinstance(other, Correspondent) and self.address == other.address

    def start(self, correspondents: Iterable) -> EmailMessage:
        response = EmailMessage()

        # Set sender
        response["From"] = self.ref

        # Set recipients
        response["To"] = ", ".join(
            [correspondent.ref for correspondent in correspondents]
        )

        # Generate some content
        completion = self.completer.complete(
            f"You are '{self.address.display_name}', your email address is '{self.address.addr_spec}'."
            "Your objective is to create a credible imaginary corporate email exchange to populate a honeypot."
            "Mention at least one invented name for projects, customers and/or problems."
            "Write a typical email expected within a corporation to any of the following correspondents:"
            + ", ".join([correspondent.ref for correspondent in correspondents])
            + "You may inspire yourself from the Ecron corpus. Any corespondent having an email within the"
            f"'{self.address.domain}' domain is a colleague of yours, others are external partners or customers."
            "First mention the subject by prefixing the line with 'Subject: ' followed by a new line and"
            "the email body. Make sure to properly format the body."
        )

        # Extract subject and body
        matches = search(
            r"Subject: (?P<subject>[^\n]+)\n+(?P<body>.+)",
            completion,
            MULTILINE | DOTALL,
        )

        response.set_content(matches.group("body").strip())
        response["Subject"] = matches.group("subject").strip()

        return response

    def respond(self, email: EmailMessage) -> EmailMessage:
        response = EmailMessage()

        # Set the subject
        response["Subject"] = (
            email["Subject"]
            if email["Subject"].startswith("RE: ")
            else f'RE: {email["Subject"]}'
        )

        # Set sender
        response["From"] = self.ref

        # Set recipients
        recipients = email["To"].split(", ")
        recipients.remove(self.ref)
        recipients.append(email["From"])
        response["To"] = ", ".join(recipients)

        # Generate a response
        completion = self.completer.complete(
            f"You are '{self.address.display_name}', your email is '{self.address.addr_spec}'."
            f"You received an email titled '{email['Subject']}' from {email['From']}"
            f"with the following correspondents in CC: {email['To']}"
            f"Correspondents within the '{self.address.domain}' domain are colleagues of you,"
            f"others are external partners or customers."
            "Make an extensive response to the following email on your behalf only."
            "Make sure to properly format the response body:\n\n"
            + quote(email.get_body().get_payload(decode=True).decode("utf8"))
        )

        response.set_content(
            f"{completion}\n\n{email['From']} wrote:\n{quote(email.get_body().get_payload(decode=True).decode('utf8'))}"
        )
        return response


if __name__ == "__main__":
    parser = ArgumentParser(
        description="emlm generates EMLs using the OpenAI Language Models"
        "(e.g. to populate honeypot networks).",
        epilog="emlm supports OpenAI, Azure and any other providers supported by https://pypi.org/project/openai/",
    )

    parser.add_argument(
        "-k",
        "--key",
        type=str,
        default=environ.get("OPENAI_API_KEY", None),
        required=environ.get("OPENAI_API_KEY", None) is None,
        help="a valid service key (OpenAI, Azure, ...)",
    )

    parser.add_argument(
        "-e",
        "--endpoint",
        type=str,
        help="an optional service API endpoint (defaults to OpenAI)",
    )

    parser.add_argument(
        "-a",
        "--address",
        type=str,
        action="append",
        metavar='"Name <upn@domain.tld>"',
        help="the possible addresses (defaults to reading line-separated entries from stdin)",
    )

    parser.add_argument(
        "-c",
        "--count",
        default=10,
        type=int,
        help="the number of conversations to generate",
    )

    parser.add_argument(
        "-d",
        "--depth",
        default=4,
        type=int,
        help="the conversation depth (i.e. number of exchanges)",
    )

    parser.add_argument(
        "--dir", default="./", help="the directory where EML files should be saved"
    )

    args = parser.parse_args()

    # Ensure addresses are defined
    if not args.address:
        args.address = [line.strip() for line in input()]

    addresses = (
        HeaderParser(policy=default)
        .parsestr(f"To: {', '.join(args.address)}")
        .get("To", [])
        .addresses
    )

    if len(addresses) < 2:
        parser.print_usage()
        parser.error("at least two addresses are required")

    # Create a completer
    completer = Completer(
        api_key=args.key,
        api_base=args.endpoint,
    )

    # Generate the correspondents
    correspondents = [
        Correspondent(address=address, completer=completer) for address in addresses
    ]

    for i in range(args.count):
        sender = choice(correspondents)
        message = sender.start(
            [
                correspondent
                for correspondent in correspondents
                if correspondent is not sender
            ]
        )
        for j in range(args.depth - 1):
            try:
                count = f"{{:0{(args.count // 10) + 1}d}}".format(i)
                depth = f"{{:0{(args.depth // 10) + 1}d}}".format(j)
                with open(
                    join(
                        args.dir, f"{sender.address.username} - {count} - {depth}.eml"
                    ),
                    mode="w",
                ) as f:
                    generator = Generator(f)
                    generator.flatten(message)

                sender = choice(
                    [
                        correspondent
                        for correspondent in correspondents
                        if correspondent is not sender
                    ]
                )
                message = sender.respond(message)
            except Exception as e:
                print(e, file=stderr)
                break

        try:
            count = f"{{:0{int(log10(args.count)) + 1}d}}".format(i)
            depth = f"{{:0{int(log10(args.depth)) + 1}d}}".format(args.depth - 1)
            with open(
                join(args.dir, f"{sender.address.username} - {count} - {depth}.eml"),
                mode="w",
            ) as f:
                generator = Generator(f)
                generator.flatten(message)
        except Exception as e:
            print(e, file=stderr)
