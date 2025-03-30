from litellm import completion
from dotenv import load_dotenv

load_dotenv()

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    },
                },
                "required": ["location"],
            },
        },
    }
]
messages = [
    {"role": "user", "content": "Hi"},
    # {
    #     "role": "assistant",
    #     "content": "I'll help you check the current weather in Boston. I'll retrieve the weather information using the get_current_weather function.",
    #     "tool_calls": [
    #         {
    #             "id": "call_abc123xyz",
    #             "type": "function",
    #             "function": {"name": "get_current_weather", "arguments": "{\"location\": \"Boston, MA\"}"}
    #         }
    #     ]
    # },
    # {
    #     "role": "tool",
    #     "tool_call_id": "call_abc123xyz",
    #     "name": "get_current_weather",
    #     "content": "{\"temperature\": \"72\", \"unit\": \"fahrenheit\", \"description\": \"Sunny\"}"
    # },
    # {"role": "assistant", "content": "The current weather in Boston is 72°F and Sunny."},
    # {"role": "user", "content": "Thanks! How about New York?"}
]


response = completion(
    model="anthropic/claude-3-5-haiku-latest",
    messages=messages,
    tools=tools,
    tool_choice="auto",
)

print(response)

#print(len(response.choices))
# print(response.choices[0].message.content)
# print(response.choices[0].message.role)
# for tool_call in response.choices[0].message.tool_calls:
#     print(tool_call)
#     print(tool_call.function.name, tool_call.function.arguments, tool_call.id)
#     function_response = "40"
#     messages.append(
#         {
#             "tool_call_id": tool_call.id,
#             "role": "tool",
#             "name": tool_call.function.name,
#             "content": function_response,
#         }
#     )

# response = completion(
#     model="anthropic/claude-3-5-haiku-latest",
#     messages=messages,
#     tools=tools,
#     tool_choice="auto",
# )