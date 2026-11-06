# Demo

## Build
Run this from the project folder in Ubuntu/WSL:

```bash
make build
```

Result from my run:

```text
[TODO: paste the actual output here]
```

## Torture commands
Run the current default torture test:

```bash
python3 ./torture --iterations 25 --seed 12345
```

Result from my run:

```text
[TODO: paste the actual output here]
```

## Manual kill session
Start the server:

```bash
mkdir -p ~/tmp_test
python3 -m src.serve ~/tmp_test/practice.db
```

When the server prints its READY line, type these requests:

```text
put w1-1 color blue
get w1-2 color
del w1-3 color
quit
```

Actual server output:

```text
[TODO: paste the actual output here]
```

## Crash-here answers

## TTL answer
