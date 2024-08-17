from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import boto3
import json
import os
from botocore.exceptions import ClientError
import random

app = FastAPI()

# Load environment variables from .env file
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
MODEL_ID = "meta.llama3-70b-instruct-v1:0"

# Initialize AWS Bedrock client
bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Enable session handling
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Initial questions
questions = [
    "Can you briefly describe your current academic journey, including any notable achievements?",
    "Are there specific fields of study or professions you are passionate about? Where do you see yourself in five years, academically or professionally?",
    "What extracurricular activities or hobbies do you enjoy that align with your academic interests?",
    "What educational resources or materials do you regularly use?"
]

def perturb_input(user_input, epsilon=0.5):
    """
    Apply local differential privacy by perturbing the input text.
    The epsilon parameter controls the noise level.
    """
    words = user_input.split()
    perturbed_words = []

    for word in words:
        # Randomly decide to perturb a word based on epsilon
        if random.random() < epsilon:
            perturbed_word = add_noise_to_word(word)
            perturbed_words.append(perturbed_word)
        else:
            perturbed_words.append(word)
    
    return " ".join(perturbed_words)

def add_noise_to_word(word):
    """
    Add synthetic noise to a word. This can involve character shuffling, 
    replacing with synonyms, or inserting random characters.
    """
    noise_type = random.choice(['shuffle', 'insert_random'])
    
    if noise_type == 'shuffle':
        return ''.join(random.sample(word, len(word)))  # Shuffling characters
    elif noise_type == 'insert_random':
        random_char = chr(random.randint(97, 122))  # Random lowercase letter
        return word[:1] + random_char + word[1:]
    else:
        return word  # Default case, no change

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Reset session variables
    request.session.clear()
    request.session['question_index'] = 0
    request.session['user_responses'] = []

    # Render template with introductory message
    return templates.TemplateResponse("chat.html", {"request": request, "intro_message": "Hi I am Naavi, your personal coach and navigator for higher education...😊"})

@app.post("/process_chat")
async def process_chat(request: Request, user_input: str = Form(...)):
    question_index = request.session.get('question_index', 0)
    user_responses = request.session.get('user_responses', [])

    # Perturb the input to apply differential privacy
    perturbed_input = perturb_input(user_input)
    
    # Ensure to store perturbed user input if not the first question
    if question_index > 0:
        user_responses.append(perturbed_input)
        request.session['user_responses'] = user_responses

    if question_index < len(questions):
        next_question = questions[question_index]
        request.session['question_index'] = question_index + 1
        return JSONResponse({'question': next_question})
    else:
        request.session['question_index'] = len(questions)  # Ensure index is at the end
        return JSONResponse({'response': "Thank you for providing the information. Please click the 'Create a Pathway' button to proceed.", 'show_pathway_button': True})

@app.get("/generate_pathway", response_class=HTMLResponse)
async def generate_pathway(request: Request):
    user_responses = request.session.get('user_responses', [])
    raw_response = await get_ai_response(user_responses)
    
    # Process the raw response to format it as desired
    pathways = format_response(raw_response)
    
    return templates.TemplateResponse("pathway.html", {"request": request, "pathway_response": pathways})

async def get_ai_response(user_responses):
    messages = "\n".join([f"user\n{response}\n" for response in user_responses])
    final_prompt = """
Based on the information provided, generate three distinct pathways for achieving the user's educational and career goals. Each pathway should be clearly separated and include step-by-step guidance. The output should be structured as follows:

Pathway 1: [Title]
  Step 1
  Step 2
  Step 3
  Step 4
  Step 5
 
 ...

Pathway 2: [Title]
  Step 1
  Step 2
  Step 3
  Step 4
  Step 5
 
 ...

Pathway 3: [Title]
  Step 1
  Step 2
  Step 3
  Step 4
  Step 5
 ...
"""

    messages += f"assistant\n{final_prompt}\n"

    try:
        native_request = {
            "prompt": messages,
            "max_gen_len": 2048,
            "temperature": 0.6,
        }
        response = bedrock_client.invoke_model(modelId=MODEL_ID, body=json.dumps(native_request))
        model_response = json.loads(response["body"].read())
        return model_response["generation"]
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Error generating AI response: {e}")

def format_response(raw_response):
    lines = raw_response.split('\n')
    formatted_response = []
    current_pathway = {"title": "", "steps": []}

    for line in lines:
        if line.startswith("Pathway "):
            if current_pathway["steps"]:
                formatted_response.append(current_pathway)
            current_pathway = {"title": line, "steps": []}
        elif line.strip():
            current_pathway["steps"].append(line.strip())

    if current_pathway["steps"]:
        formatted_response.append(current_pathway)
    
    return formatted_response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
