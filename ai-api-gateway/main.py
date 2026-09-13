# main.py

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import os
import time
import glob
import random
import xml.etree.ElementTree as ET
import uuid
from apis.openai import OpenAIModel
from apis.local import LocalModel

# Global variable for provider selection
SELECTED_PROVIDER = os.environ.get("AI_PROVIDER", "local").lower()  # Defaults to "local"

app = FastAPI()

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#SYSTEM_PROMPT = """You are Mixtral, a local AI assistant. You can communicate with another local AI assistant named WizardCoder-17b by sending a <wizard_task></wizard_task> (which the application will route and send to WizardCoder-17b). WizardCoder-17b's responses will be sent back to you."""
SYSTEM_PROMPT_MIXTRAL = """
You are Mixtral, a local AI assistant. Your role is to engage in a conversation with the user and provide helpful responses.
During the conversation, you can use the following tags to structure your responses:

<Response_to_User>: Use this tag to provide a direct response to the user's input. The content within these tags will be displayed in the main chat window.

<questions_for_user>: Use this tag to ask questions to the user. The questions within these tags will be displayed to the right of the main chat window. Each question should be on a new line.

<tasks>: Use this tag to specify any tasks or action items related to the conversation. The tasks within these tags will be displayed below the questions_for_user section. Each task should be on a new line.

<wizard_task>: Use this tag to send tasks or queries to another AI assistant named WizardCoder-17b. The content within these tags will be sent to WizardCoder-17b for processing, and the response will be sent back to you.

Please structure your responses using these tags to ensure proper communication and display of information to the user.
"""

SYSTEM_PROMPT_WIZARD = """
You are WizardCoder-17b, a local AI assistant specializing in coding and technical tasks. Your role is to assist Mixtral by providing responses to the tasks or queries sent by Mixtral.

Mixtral will send you tasks or queries wrapped in <wizard_task> tags. Your responsibility is to process these tasks, provide the necessary code snippets, explanations, or technical information, and send the response back to Mixtral.

When providing your response, please use the following tags:

<wizard_response>: Wrap your entire response within these tags. This will help Mixtral identify and process your response correctly.

<code>: If your response includes any code snippets, please wrap them within <code> tags. This will ensure proper formatting when displayed to the user.

<explanation>: If your response includes any explanations or additional information related to the task, please wrap them within <explanation> tags.

Please make sure to structure your response using these tags and provide the requested information accurately and concisely.
"""
MAX_ITERATIONS = 4000
MAX_REQUESTS_PER_MINUTE = 15
MAX_TOKENS_PER_MINUTE = 450000
DELAY_AFTER_REQUESTS = 5
DELAY_DURATION = 5

long_memory = []
short_memory = []

request_count = 0
token_count = 0
last_request_time = time.time()
last_token_time = time.time()

class TaskFile:
    def __init__(self, task_id):
        self.task_id = task_id
        self.root = ET.Element("task")
        self.root.set("id", str(task_id))

    def add_element(self, tag, text):
        element = ET.SubElement(self.root, tag)
        element.text = text

    def save(self):
        tree = ET.ElementTree(self.root)
        filename = f"task_{self.task_id}.xml"
        tree.write(filename)

class Mixtral:
    def __init__(self):
        self.local_model = LocalModel() # Keep for local wizard if nothing else
        self.openai_model = None
        
        # Initialize the selected provider with proper error handling
        try:
            if SELECTED_PROVIDER == "openai":
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    print("Warning: OPENAI_API_KEY not set. Falling back to local provider for Mixtral.")
                    print("Using local provider for Mixtral.")
                else:
                    self.openai_model = OpenAIModel()
                    print("Using OpenAI provider.")
            else:
                print("Using local provider for Mixtral.")
        except Exception as e:
            print(f"Error initializing provider {SELECTED_PROVIDER}: {e}")
            print("Falling back to local provider.")
            
        self.wizard_queue = []

    def process_task(self, task_id, user_input):
        task_file = TaskFile(task_id)
        task_file.add_element("user_input", user_input)

        mixtral_response = self.phase_one(user_input, task_id)

        task_file.add_element("mixtral_response", mixtral_response)
        task_file.save()

        return mixtral_response

    def phase_one(self, user_input, task_id):
        global request_count, token_count

        system_prompt = SYSTEM_PROMPT_MIXTRAL
        refined_input = user_input
        total_input_tokens = 0
        total_output_tokens = 0

        for i in range(MAX_ITERATIONS):
            print(f"Iteration {i + 1} - Sending request to the model...")

            self.wait_for_rate_limit()

            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": refined_input}]

            mixtral_response_content = ""
            input_tokens = 0
            output_tokens = 0

            if SELECTED_PROVIDER == "openai" and self.openai_model:
                # Assuming you have a default OpenAI model name, e.g., "gpt-3.5-turbo-0125"
                # This model name should ideally come from config.json or be a parameter
                openai_model_name_key = "gpt-3.5-turbo-0125" # This is a key in apis/config.json for OpenAI
                mixtral_response_content, input_tokens, output_tokens = self.openai_model.process_openai_model(
                    openai_model_name_key, messages, 0.5, 100 # Max tokens might need adjustment
                )
            else: # Default or fallback to local
                mixtral_response_content, input_tokens, output_tokens = self.local_model.process_local_model(
                    "mixtral-8x7b-local", messages, 0.5, 100
                )

            request_count += 1
            token_count += input_tokens + output_tokens
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens

            print(f"Iteration {i + 1} - Model output received:")
            print(mixtral_response_content)
            print()

            questions_from_user = self.extract_questions_for_user(mixtral_response_content)
            if questions_from_user and (i == MAX_ITERATIONS // 2 - 1 or i == MAX_ITERATIONS - 1):
                self.pause_for_questions(questions_from_user)

            if "<internal_monologue>" in mixtral_response_content:
                internal_monologue = self.extract_internal_monologue(mixtral_response_content)
            else:
                internal_monologue = ""

            print(f"Iteration {i + 1} - Internal monologue:")
            print(internal_monologue)
            print()

            long_memory.append(internal_monologue)
            if len(short_memory) < 5:
                short_memory.append(internal_monologue)
            else:
                short_memory.pop(0)
                short_memory.append(internal_monologue)

            system_prompt = self.analyze_and_refine_prompt(internal_monologue, system_prompt)
            refined_input = mixtral_response_content

            if (i + 1) % DELAY_AFTER_REQUESTS == 0:
                print(f"Pausing for {DELAY_DURATION} seconds after {DELAY_AFTER_REQUESTS} requests...")
                time.sleep(DELAY_DURATION)

        # Process wizard tasks from the queue
        while self.wizard_queue:
            wizard_task = self.wizard_queue.pop(0)
            wizard_messages = [{"role": "system", "content": SYSTEM_PROMPT_WIZARD}, 
                              {"role": "user", "content": wizard_task}]
            wizard_response_content, wizard_input_tokens, wizard_output_tokens = self.local_model.process_local_model(
                "WizardCoder-17b", wizard_messages, 0.5, 100)
            token_count += wizard_input_tokens + wizard_output_tokens  # Update token count
            refined_input += f"\nWizard response: {wizard_response_content}"

        return self.format_response(refined_input)
    def format_response(self, response):
        response_to_user = self.extract_tag(response, "Response_to_User")
        questions_for_user = self.extract_tag(response, "questions_for_user")
        tasks = self.extract_tag(response, "tasks")
        wizard_tasks = self.extract_tag(response, "wizard_task")

        self.wizard_queue.extend(wizard_tasks)

        formatted_response = {
            "response_to_user": response_to_user,
            "questions_for_user": questions_for_user,
            "tasks": tasks
        }

        return formatted_response

    def extract_tag(self, content, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start_index = content.find(start_tag)
        end_index = content.find(end_tag)

        if start_index != -1 and end_index != -1:
            start_index += len(start_tag)
            return content[start_index:end_index].strip()
        else:
            return ""
    def wait_for_rate_limit(self):
        global last_request_time, last_token_time, request_count, token_count

        current_time = time.time()

        if request_count >= MAX_REQUESTS_PER_MINUTE:
            elapsed_time = current_time - last_request_time
            if elapsed_time < 60:
                wait_time = 60 - elapsed_time
                print(f"Request rate limit exceeded. Waiting for {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                last_request_time = time.time()
                request_count = 0

        if token_count >= MAX_TOKENS_PER_MINUTE:
            elapsed_time = current_time - last_token_time
            if elapsed_time < 60:
                wait_time = 60 - elapsed_time
                print(f"Token rate limit exceeded. Waiting for {wait_time:.2f} seconds...")
                time.sleep(wait_time)
                last_token_time = time.time()
                token_count = 0

    def extract_questions_for_user(self, content):
        start_tag = "<questions_for_user>"
        end_tag = "</questions_for_user>"
        start_index = content.find(start_tag) + len(start_tag)
        end_index = content.find(end_tag)
        if start_index != -1 and end_index != -1:
            questions_text = content[start_index:end_index].strip()
            questions = [q.strip() for q in questions_text.split("\n") if q.strip()]
            return questions
        return []

    def pause_for_questions(self, questions_from_user):
        if questions_from_user:
            print("Questions for the user:")
            for question in questions_from_user:
                print(question)
            print("Please take a moment to consider these questions.")
            print("You have 90 seconds to provide your response.")
            print("Press Enter to start the timer...")
            input()

            start_time = time.time()
            user_response = input("Your response (or press Enter to skip): ")
            elapsed_time = time.time() - start_time

            if elapsed_time > 90:
                print("Time's up! Continuing with the feedback loop.")
            else:
                print(f"Your response was: {user_response}")
        else:
            print("No questions to display.")

    def analyze_and_refine_prompt(self, internal_monologue, system_prompt):
        print("Analyzing and refining prompt...")
        refined_prompt = system_prompt + " " + internal_monologue

        if long_memory:
            sample_size = random.randint(1, len(long_memory))
            long_memory_sample = random.sample(long_memory, sample_size)
            refined_prompt += " ".join(long_memory_sample)

        if short_memory:
            sample_size = random.randint(1, len(short_memory))
            short_memory_sample = random.sample(short_memory, sample_size)
            refined_prompt += " ".join(short_memory_sample)

        print("Refined prompt:", refined_prompt)
        print()
        return refined_prompt

    def extract_internal_monologue(self, content):
        start_tag = "<internal_monologue>"
        end_tag = "</internal_monologue>"
        start_index = content.find(start_tag) + len(start_tag)
        end_index = content.find(end_tag)
        internal_monologue = content[start_index:end_index].strip()
        return internal_monologue

mixtral = Mixtral()

class InputData(BaseModel):
    user_input: str
    task_id: int

@app.get("/")
@app.get("/index.html")
async def serve_html():
    try:
        with open("index.html", "r") as file:
            html_content = file.read()
        return HTMLResponse(content=html_content, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>SiloedBoss API Management</h1><p>Web interface not found.</p>", status_code=404)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error</h1><p>Failed to load interface: {str(e)}</p>", status_code=500)

@app.get("/health")
async def health_check():
    """Health check endpoint for deployment monitoring."""
    return {
        "status": "healthy",
        "provider": SELECTED_PROVIDER,
        "timestamp": time.time()
    }

@app.post("/process")
async def process_input(input_data: InputData):
    try:
        server_task_id = str(uuid.uuid4())
        mixtral_ai_response = mixtral.process_task(server_task_id, input_data.user_input)

        # Create a new dictionary for the response payload
        response_payload = mixtral_ai_response.copy() # Start with the AI's structured response
        response_payload["task_id"] = server_task_id # Add the server-generated task_id

        return response_payload
    except Exception as e:
        print(f"Error processing task: {str(e)}")
        return {"message": "An error occurred while processing the task."}

@app.get("/task-history")
async def get_task_history():
    tasks = []
    for filename in glob.glob("task_*.xml"):
        try:
            task_id = filename.replace("task_", "").replace(".xml", "")
            tasks.append({"id": task_id})
        except Exception as e:
            # Log error or handle cases where filename might not be as expected
            print(f"Error processing filename {filename}: {e}")
    return {"tasks": tasks}
