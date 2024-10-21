# malachite

Email domain banlist manager

Malachite stores a list of patterns (domains and IP addresses) for known bad email providers.

When a user registers or changes the email on their account, malachite will resolve the MX, A,
and AAAA records of the email address's domain. If it matches an item on the banlist, a services
`BADMAIL` entry is added for that domain, and the account is `FDROP`ed (if registering) or
`FREEZE`'d (if changing the email). If `FDROP`ed, the user is sent a `NOTICE`, asking them to
try a different email address.

## Setup

```sh
cp config.example.toml config.toml
$EDITOR config.toml
psql -U malachite -f make-database.sql
```

## Running

```
python3 -m malachite config.toml
```

## Commands

TODO
