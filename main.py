# main.py
import sys
from agent import run_agent
from llm import call_llm



def print_usage():
    print("Usage:")
    print('  python main.py run "your message"')
    print('  python main.py resume <thread_id> "your message"')


def main():
    if len(sys.argv) < 2:
        print_usage()
        return 

    command = sys.argv[1]

    if command == "run":
        if len(sys.argv) >= 3:
            user_input = " ".join(sys.argv[2:])
        else:
            user_input = input("User: ")
        
        result = run_agent(user_input, call_llm, thread_id=None)
    elif command == "resume":
        if len(sys.argv) < 4:
            print_usage()
            return
        thread_id = sys.argv[2]
        user_input = " ".join(sys.argv[3:])
        result = run_agent(user_input, call_llm, thread_id=thread_id)
    else:
        print_usage()
        return
    
    print("\nTHREAD:")
    print(result["thread_id"])

    print("\nTURN:")
    print(result["turn_id"])

    print("\nFINAL:")
    print(result["answer"])


if __name__ == "__main__":
    main()