# SPADE: Semantic Pattern-Guided LLM-Based Multi-Agent DebatE for Automated Program Repair


## Environment
```bash
# Make the script executable 
chmod +x setup.sh

# Run the setup script
./setup.sh
```

## Running SPADE
```bash
# Activate the virtual environment (if setup.sh doesn't do it automatically)
source .venv/bin/activate

# Start the evaluation
python main.py
```

### Tip: Resetting Agent Memory

```bash
# Delete the local checkpointer database to clear agent memory
rm data/checkpoints.sqlite*
```


