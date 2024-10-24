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

```sh
python3 -m malachite config.toml
```

## Commands

**ADD**
```
usage: ADD <ip|cidr|domain|%glob%|/regex/> <reason>
  add a pattern to the mxbl. globs and regexes are case-insensitive
```

**DEL**
```
usage: DEL <id>
  remove a pattern from the mxbl
```

**EDITPATTERN**
```
usage: EDITPATTERN <id> <ip|cidr|domain|%glob%|/regex/>
  update the pattern of an entry by id
```

**EDITREASON**
```
usage: EDITREASON <id> <reason>
  update the reason for an entry by id
```

**GET**
```
usage: GET <id>
  get information about an entry
```

**HELP**
```
usage: HELP [command]
  show usage information for a command
```

**LIST**
```
usage: LIST [limit = 0] [offset = 0]
  list mxbl entries up to limit (default: no limit),
  starting at offset (default: index 0)
```

**SETTINGS**
```
usage: SETTINGS <GET|GETALL|SET> [name] [value]
  update dynamic settings for the bot
```

> *currently accepted settings:*
> - **pause**: `0` for normal operation, `1` to only warn

**TEST**
```
usage: TEST <email|domain>
  test if an email or domain would match an existing pattern
```

**TESTPAT**
```
usage: TESTPAT <ip|cidr|domain|%glob%|/regex/> <email|domain>
  test if an email or domain would match a specified pattern
```

**TOGGLE**
```
usage: TOGGLE <id>
  make an entry active or warn
```
