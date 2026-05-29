# main.py
import sys
from agent import run_agent
from llm import call_llm

if __name__ == "__main__":
    user_input = " ".join(sys.argv[1:]) or input("User: ")
    answer = run_agent(user_input, call_llm)
    print("\nFINAL:")
    print(answer)