import gradio as gr
import backend_logic # Import the backend logic
import threading # Need threading for voice input polling

# Instantiate the backend logic class
app_logic = backend_logic.AppLogic()

# --- State Variables for Gradio ---
# These mirror some states from AppLogic but are managed by Gradio
# for passing between function calls within a session.
# We'll use a single state dictionary for simplicity.
initial_state = {
    "current_mode": "main", # 'main', 'teaching', 'exam', 'history_list', 'history_detail', 'wrong_book_types', 'wrong_book_list', 'wrong_book_detail'
    "conversation_history": [],
    "current_dialog_key": None,
    "exam_questions": [],
    "current_question_index": 0,
    "user_answers": {},
    "evaluation_results": {},
    "history_list_data": [], # Store data for history list view
    "wrong_data": {}, # Store all wrong data for wrong book views
    "wrong_filtered_list": [], # Store filtered wrong question list
    "voice_input_status": "stopped", # 'stopped', 'running', 'processing'
    "last_voice_text": None # Store the last recognized text
}

# --- Helper Functions for UI Updates ---
# These functions take the state and return component visibility/values

def set_mode(state, mode):
    """Updates the current mode in state."""
    state["current_mode"] = mode
    # print(f"Mode set to: {mode}")
    return state

def get_main_menu_visibility(state):
    return gr.update(visible=state["current_mode"] == "main")

def get_teaching_mode_visibility(state):
    return gr.update(visible=state["current_mode"] == "teaching")

def get_exam_mode_visibility(state):
    return gr.update(visible=state["current_mode"] == "exam")

def get_history_list_visibility(state):
     return gr.update(visible=state["current_mode"] == "history_list")

def get_history_detail_visibility(state):
     return gr.update(visible=state["current_mode"] == "history_detail")

def get_wrong_book_types_visibility(state):
     return gr.update(visible=state["current_mode"] == "wrong_book_types")

def get_wrong_book_list_visibility(state):
     return gr.update(visible=state["current_mode"] == "wrong_book_list")

def get_wrong_book_detail_visibility(state):
     return gr.update(visible=state["current_mode"] == "wrong_book_detail")

def get_voice_button_label(state):
    return gr.update(value="停止语音输入" if state["voice_input_status"] == "running" else "语音输入")

def get_exam_nav_buttons_visibility(state):
    current_index = state.get("current_question_index", 0)
    total_questions = len(state.get("exam_questions", []))
    is_exam_mode = state["current_mode"] == "exam"

    prev_visible = is_exam_mode and current_index > 0
    next_visible = is_exam_mode and current_index < total_questions - 1
    submit_visible = is_exam_mode and current_index == total_questions - 1

    return gr.update(visible=prev_visible), gr.update(visible=next_visible), gr.update(visible=submit_visible)


# --- Event Handlers (calling backend_logic) ---

def start_teaching_mode(state):
    """Switches to teaching mode and resets state."""
    # Save current mode data if applicable before switching
    if state["current_mode"] == "teaching":
         app_logic.save_chat_history()
    elif state["current_mode"] == "exam":
         app_logic.save_wrong_questions()

    app_logic.reset_teaching_state() # Reset backend state
    state = set_mode(state, "teaching")
    state["conversation_history"] = app_logic.conversation_history # Sync state
    state["current_dialog_key"] = app_logic.current_dialog_key # Sync state
    return state, [], "" # Return updated state, clear chatbot, clear chat input


def start_exam_mode(state):
    """Generates exam questions and switches to exam mode."""
    # Save current mode data if applicable before switching
    if state["current_mode"] == "teaching":
         app_logic.save_chat_history()
    elif state["current_mode"] == "exam":
         app_logic.save_wrong_questions()

    app_logic.reset_exam_state() # Reset backend state
    questions, error = app_logic.generate_exam_questions()

    if error:
        # Stay on main menu and show error
        state = set_mode(state, "main")
        return state, [], 0, {}, {}, gr.update(value=f"生成考题失败: {error}", visible=True)

    state = set_mode(state, "exam")
    state["exam_questions"] = questions
    state["current_question_index"] = 0
    state["user_answers"] = {} # Ensure user answers are reset
    state["evaluation_results"] = {} # Ensure evaluation results are reset

    return state, questions, 0, state["user_answers"], state["evaluation_results"], gr.update(visible=False) # Return state, questions, current index, answers, eval results, hide message box


def view_chat_history_list(state):
    """Loads chat history list and switches to history list mode."""
    # Save current mode data if applicable before switching
    if state["current_mode"] == "teaching":
         app_logic.save_chat_history()
    elif state["current_mode"] == "exam":
         app_logic.save_wrong_questions()

    history_list_data, full_chat_data = app_logic.load_chat_history_list()
    state = set_mode(state, "history_list")
    state["history_list_data"] = history_list_data # Store list data for display
    state["chat_data_full"] = full_chat_data # Store full data for drill down

    # Prepare history list for Gradio display (e.g., as Markdown list)
    display_text = "## 聊天记录\n\n"
    if not history_list_data:
        display_text += "暂无聊天记录。"
    else:
        for i, (key, preview) in enumerate(history_list_data):
            # Create a link-like text that can be identified and clicked (requires JS or specific component)
            # For simplicity, let's just list them and the user would select from a dropdown or similar.
            # Or we dynamically create buttons (complex with just Blocks without helper functions).
            # Let's return structured data that can be displayed by gr.DataFrame or similar.
            pass # Will handle display in the UI block

    return state, history_list_data # Return state and list data


def view_chat_detail(state, dialog_key):
    """Loads and displays a specific chat dialogue."""
    # Ensure full chat data is loaded or available in state
    if "chat_data_full" not in state or not state["chat_data_full"]:
         # Should not happen if coming from history list, but as a fallback
         _, full_chat_data = app_logic.load_chat_history_list()
         state["chat_data_full"] = full_chat_data
         if not state["chat_data_full"]:
              state = set_mode(state, "history_list") # Go back if data not found
              return state, [], "无法加载聊天详情，请重试。" # Return state, empty chat, error message

    conversation, error = app_logic.load_chat_detail(state["chat_data_full"], dialog_key)

    if error:
        state = set_mode(state, "history_list") # Go back if error
        return state, [], error # Return state, empty chat, error message

    state = set_mode(state, "history_detail")
    state["conversation_history"] = conversation # Load into current history for viewing/continuation
    state["current_dialog_key"] = dialog_key # Set current key for continuation

    # Format conversation for Chatbot display
    chatbot_display = []
    for msg in conversation:
         if msg["role"] == "user":
             chatbot_display.append([msg["content"], None]) # User message
         elif msg["role"] == "assistant":
             chatbot_display.append([None, msg["content"]]) # Assistant message

    return state, chatbot_display, None # Return state, chatbot format, no error


def continue_conversation_from_history(state):
     """Switches to teaching mode with loaded history."""
     state = set_mode(state, "teaching")
     # The conversation_history is already loaded in load_chat_detail
     # Need to format it for the chatbot
     chatbot_display = []
     for msg in state["conversation_history"]:
          if msg["role"] == "user":
              chatbot_display.append([msg["content"], None])
          elif msg["role"] == "assistant":
              chatbot_display.append([None, msg["content"]])
     return state, chatbot_display, "" # Return state, chatbot format, clear input


def delete_chat_record_action(state, dialog_key_to_delete):
     """Deletes a specific chat record and refreshes the list."""
     if not dialog_key_to_delete:
          return state, [], "请先选择要删除的记录。" # No key selected

     message = app_logic.delete_chat_record(dialog_key_to_delete)
     # After deleting, refresh the history list view
     history_list_data, full_chat_data = app_logic.load_chat_history_list()
     state["history_list_data"] = history_list_data
     state["chat_data_full"] = full_chat_data

     # Stay on history list view
     state = set_mode(state, "history_list")

     return state, history_list_data, message # Return state, refreshed list, message


def view_wrong_book_types(state):
     """Switches to wrong book types view."""
     # Save current mode data if applicable before switching
     if state["current_mode"] == "teaching":
         app_logic.save_chat_history()
     elif state["current_mode"] == "exam":
         app_logic.save_wrong_questions()

     state = set_mode(state, "wrong_book_types")
     wrong_data, error = app_logic.load_wrong_questions()
     state["wrong_data"] = wrong_data # Store all wrong data

     # Determine if there are questions of each type to potentially show buttons
     has_choice = any(q.get("type") == "选择" for q in wrong_data.values())
     has_fill = any(q.get("type") == "填空" for q in wrong_data.values())
     has_open = any(q.get("type") == "简答" for q in wrong_data.values())

     return state, gr.update(visible=has_choice), gr.update(visible=has_fill), gr.update(visible=has_open) # Return state and button visibilities


def view_wrong_book_list(state, question_type):
     """Loads and displays wrong questions of a specific type."""
     filtered_questions, error = app_logic.load_wrong_questions_by_type(question_type)

     if error:
          state = set_mode(state, "wrong_book_types") # Go back on error
          # Need a way to display error message in the type view or main view
          # Let's just return the state and handle error display in UI
          return state, [], error # Return state, empty list, error message

     state = set_mode(state, "wrong_book_list")
     state["wrong_filtered_list"] = list(filtered_questions.items()) # Store as list of (key, data) tuples
     state["current_wrong_type"] = question_type # Store current type for 'Back' button

     # Prepare data for Gradio display (e.g., DataFrame)
     display_list = [{"key": key, "preview": q["description"][:50]} for key, q in filtered_questions.items()]

     return state, display_list, "" # Return state, display data, clear message


def view_wrong_book_detail(state, wrong_question_key):
    """Loads and displays the detail of a specific wrong question."""
    # Ensure wrong_data is loaded
    if "wrong_data" not in state or not state["wrong_data"]:
         wrong_data, error = app_logic.load_wrong_questions()
         state["wrong_data"] = wrong_data
         if error:
             state = set_mode(state, "wrong_book_types")
             return state, {}, error # Return state, empty detail, error

    question_detail = state["wrong_data"].get(wrong_question_key)

    if not question_detail:
        state = set_mode(state, "wrong_book_list") # Go back if question not found
        return state, {}, f"未找到错题 '{wrong_question_key}'。" # Return state, empty detail, error

    state = set_mode(state, "wrong_book_detail")
    state["current_wrong_key"] = wrong_question_key # Store key for delete/back
    state["current_wrong_type"] = question_detail.get("type", "未知") # Store type for back button

    # Prepare detail for display
    detail_display = {
        "题目描述": question_detail.get("description", "无"),
        "类型": question_detail.get("type", "无"),
        "你的答案": question_detail.get("user_answer", "无"),
        "正确答案": question_detail.get("answer", "无"),
        "答案解释": question_detail.get("explanation", "无"),
        "选项": question_detail.get("options", "无") if question_detail.get("type") == "选择" else "非选择题"
    }


    return state, detail_display, "" # Return state, detail dictionary, clear message


def delete_wrong_question_action(state):
     """Deletes the currently viewed wrong question and returns to the list."""
     if "current_wrong_key" not in state or not state["current_wrong_key"]:
          return state, [], "没有选中要删除的错题。" # No key selected

     dialog_key_to_delete = state["current_wrong_key"]
     message = app_logic.delete_wrong_question(dialog_key_to_delete)

     # After deleting, refresh the list view for the current type
     wrong_type = state.get("current_wrong_type", "选择") # Default or use stored type
     filtered_questions, error = app_logic.load_wrong_questions_by_type(wrong_type)
     state["wrong_data"], _ = app_logic.load_wrong_questions() # Also refresh full data
     state["wrong_filtered_list"] = list(filtered_questions.items())

     # Go back to the list view
     state = set_mode(state, "wrong_book_list")

     # Prepare data for Gradio display (e.g., DataFrame)
     display_list = [{"key": key, "preview": q["description"][:50]} for key, q in filtered_questions.items()]


     return state, display_list, message # Return state, refreshed list, message


def return_to_main_menu(state):
    """Saves current state and returns to main menu."""
    # Save current mode data if applicable before switching
    if state["current_mode"] == "teaching":
         app_logic.save_chat_history()
    elif state["current_mode"] == "exam":
         app_logic.save_wrong_questions()

    state = set_mode(state, "main")
    # Clear transient data related to specific modes
    state["conversation_history"] = []
    state["current_dialog_key"] = None
    state["exam_questions"] = []
    state["current_question_index"] = 0
    state["user_answers"] = {}
    state["evaluation_results"] = {}
    state["history_list_data"] = []
    state["chat_data_full"] = {}
    state["wrong_data"] = {}
    state["wrong_filtered_list"] = []
    state["current_wrong_key"] = None
    state["current_wrong_type"] = None

    # Stop voice recognition if running
    if backend_logic.voice_recognition_active:
         backend_logic.stop_voice_recognition_thread()
         state["voice_input_status"] = "stopped"


    return state, gr.update(value="语音输入") # Return state, reset voice button


# --- Teaching Mode Handlers ---
def send_message(state, user_input):
    """Sends user message and gets AI response."""
    if not user_input:
        # Return current state and chatbot display without changes
        chatbot_display = []
        for msg in state["conversation_history"]:
            if msg["role"] == "user":
                chatbot_display.append([msg["content"], None])
            elif msg["role"] == "assistant":
                chatbot_display.append([None, msg["content"]])
        return state, chatbot_display, "", "" # state, chatbot, clear input, clear voice text

    # Add user message to backend history
    app_logic.conversation_history = state["conversation_history"] # Sync backend history
    app_logic.conversation_history.append({"role": "user", "content": user_input})
    state["conversation_history"] = app_logic.conversation_history # Sync state

    # Call backend to get AI response
    # backend_logic.send_message handles the API call and appending to its history
    # We need to adapt it to work with the history passed from state or sync back
    # Let's refactor backend_logic.send_message to take history and return new history + AI message
    # --- Adaptation needed in backend_logic.py ---
    # For now, let's just sync history, call the original send_message, and sync back.
    # A better approach is to rewrite send_message in backend to take history, add user msg, call API, add AI msg, return updated history.
    # Assuming send_message is updated to return the full updated history and the AI message text:
    # updated_history, ai_message_text = app_logic.send_message_adapted(state["conversation_history"], user_input)
    # state["conversation_history"] = updated_history
    # But given the original structure, let's try syncing.

    # Temporary: Directly call original logic, assuming it modifies its internal state
    # This couples frontend and backend state more tightly than ideal.
    # app_logic.conversation_history = state["conversation_history"] # Ensure backend is synced
    # try:
    #      # Original logic gets response and appends to app_logic.conversation_history
    #      # This needs refactoring in backend_logic to return the new AI message
    #      # For now, just call and assume backend updates its state, then sync back
    #      # This is not a clean pattern for Gradio.
    #      # Need a proper function in backend_logic like:
    #      # def get_ai_response(self, history, user_input):
    #      #    # add user_input to history, call API, add response, return new history
    #      #    pass
    #      pass # Placeholder

    # Let's simulate the response for now until backend_logic.send_message is adapted to return response
    # In a real scenario, you call app_logic.send_message() and it updates its state.
    # Then you sync the state back.
    try:
         # Call backend logic to get AI response based on current history
         # This backend call should get the history, add user input, get AI response, add AI response.
         # Let's assume backend_logic has a method like process_chat_message(self, user_input)
         # that handles the API call and updates its internal self.conversation_history
         # Then we sync state back.
         # --- Needs refactoring in backend_logic ---
         # Example of adapted backend_logic.send_message:
         # def send_message(self, user_input):
         #     self.conversation_history.append({"role": "user", "content": user_input})
         #     # API call...
         #     assistant_message = ... # Get AI message
         #     self.conversation_history.append({"role": "assistant", "content": assistant_message})
         #     return assistant_message # Return the AI message text
         pass # Placeholder

    # Let's implement a simple version here that calls a simplified backend function
    # that just takes history, adds user, calls API, adds assistant, and returns new history + AI msg
    # Need to add/adapt this method in backend_logic.py
    assistant_message = ""
    try:
        # Call OpenAI API directly here for demonstration, ideally in backend
        # This is a temporary placement for demo purposes.
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=state["conversation_history"]
        )
        assistant_message = response['choices'][0]['message']['content']
        app_logic.conversation_history = state["conversation_history"] # Sync backend
        app_logic.conversation_history.append({"role": "assistant", "content": assistant_message})
        state["conversation_history"] = app_logic.conversation_history # Sync state
    except Exception as e:
        assistant_message = f"Error: 调用 OpenAI API 出错: {e}"
        # Decide how to handle error in history - maybe add as an AI message?
        app_logic.conversation_history = state["conversation_history"] # Sync backend
        app_logic.conversation_history.append({"role": "assistant", "content": assistant_message})
        state["conversation_history"] = app_logic.conversation_history # Sync state


    # Format history for Chatbot display
    chatbot_display = []
    for msg in state["conversation_history"]:
         if msg["role"] == "user":
             chatbot_display.append([msg["content"], None])
         elif msg["role"] == "assistant":
             chatbot_display.append([None, msg["content"]])


    return state, chatbot_display, "", "" # Return state, updated chatbot, clear input, clear voice text


def toggle_voice_input(state):
    """Starts or stops voice input."""
    if state["voice_input_status"] == "stopped":
        status = backend_logic.start_voice_recognition_thread()
        state["voice_input_status"] = "running" if "停止" in status else "stopped" # Update state based on backend
        return state, status # Return state and new button label
    else: # status is 'running'
        status = backend_logic.stop_voice_recognition_thread()
        state["voice_input_status"] = "stopped" # Update state
        return state, status # Return state and new button label

def poll_voice_input(state):
    """Polls for voice recognition results."""
    if state["voice_input_status"] == "running":
        result = backend_logic.get_voice_recognition_result()
        if result and result != "[STOPPED]" and not result.startswith("[Error:"):
            state["last_voice_text"] = result # Store result in state
            # Optionally, update the input box immediately with the result
            # But updating an input box from a background poll is tricky in Gradio.
            # A common pattern is to have a button "Use Voice Text" triggered by polling.
            # Or update a dedicated "Recognized Text" display area.
            # Let's update a separate textbox and the input box value.
            return state, result, result # Return state, recognized text, update input box
        elif result == "[STOPPED]" or result.startswith("[Error:"):
             # Recognition stopped or had an error
             state["voice_input_status"] = "stopped"
             error_msg = result if result.startswith("[Error:") else ""
             # Update button label via state change, might need extra trigger
             return state, f"识别结束。{error_msg}", "", "" # Update state, recognized text display, clear input?
        else:
             # No new result
             return state, state["last_voice_text"] or "", "", "" # Return state, current recognized text, keep input, keep voice text

    return state, state["last_voice_text"] or "", "", "" # Return current state and values if not running


# --- Exam Mode Handlers ---

def show_question(state, index):
    """Displays a specific exam question."""
    questions = state.get("exam_questions", [])
    if not questions or not (0 <= index < len(questions)):
        # Should not happen if navigation is correct, but as a safeguard
        state["current_question_index"] = 0
        return state, {}, None, None, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), "" # State, question_data, answer_value, eval_display, nav button visibilities, error

    question = questions[index]
    state["current_question_index"] = index

    # Prepare question data for display
    question_display = {
        "index": index + 1, # 1-based index for display
        "total": len(questions),
        "type": question.get("type", "未知"),
        "description": question.get("description", "无描述"),
        "options": question.get("option", None), # Only for choice
    }

    # Get user's saved answer for this question, if any
    user_answer_value = state["user_answers"].get(index, None)
    if question_display["type"] == "选择" and user_answer_value is not None:
         # For radio buttons, the value should match one of the option keys (A, B, C, D)
         pass # Value is already the option key


    # Get evaluation result for this question, if available
    evaluation = state["evaluation_results"].get(index, None)
    evaluation_display_text = ""
    if evaluation:
        evaluation_display_text = (
            f"评判结果: {evaluation.get('result', 'N/A')}\n"
            f"得分: {evaluation.get('score', 'N/A')}\n"
            f"评分理由: {evaluation.get('reason', '无')}\n"
            f"参考答案: {evaluation.get('correct_answer', '无')}\n"
            f"答案解释: {evaluation.get('explanation', '无')}"
        )

    # Determine navigation button visibility
    nav_prev_visible = index > 0
    nav_next_visible = index < len(questions) - 1
    nav_submit_visible = index == len(questions) - 1

    # Clear any previous error messages
    error_message = ""

    return (state, question_display, user_answer_value, evaluation_display_text,
            gr.update(visible=nav_prev_visible),
            gr.update(visible=nav_next_visible),
            gr.update(visible=nav_submit_visible),
            error_message) # Return state and display data/visibility updates


def save_answer(state, user_answer):
    """Saves the user's answer for the current question."""
    current_index = state.get("current_question_index", 0)
    state["user_answers"][current_index] = user_answer
    # print(f"Saved answer for question {current_index}: {user_answer}")
    return state # Return updated state

def submit_exam(state):
    """Submits the exam for evaluation."""
    total_score, evaluation_results, error = app_logic.submit_exam()

    state["evaluation_results"] = evaluation_results
    state["total_score"] = total_score # Store total score

    if error:
        # Stay on exam mode, maybe show an error message
        return state, gr.update(value=f"提交考试出错: {error}", visible=True), total_score # State, message, score (might be 0)

    # Exam submitted, show results? Or return to the first question to view evaluations?
    # Original code showed total score message box then returned to the first question.
    # Let's show a message box via a component and return to the first question.
    state["current_question_index"] = 0 # Go back to the first question to view results

    # Prepare message box content
    message_content = f"考试已提交。你的总得分是: {total_score}"

    # Need to re-render the first question with evaluation results
    # Call show_question for the first question (index 0)
    questions = state.get("exam_questions", [])
    if not questions: # Should not happen if submit was possible
         return state, gr.update(value="没有题目可显示。", visible=True), total_score # State, message, score
    question = questions[0]
    question_display = {
        "index": 1,
        "total": len(questions),
        "type": question.get("type", "未知"),
        "description": question.get("description", "无描述"),
        "options": question.get("option", None),
    }
    user_answer_value = state["user_answers"].get(0, None)
    evaluation_display_text = ""
    first_q_evaluation = state["evaluation_results"].get(0, None)
    if first_q_evaluation:
        evaluation_display_text = (
            f"评判结果: {first_q_evaluation.get('result', 'N/A')}\n"
            f"得分: {first_q_evaluation.get('score', 'N/A')}\n"
            f"评分理由: {first_q_evaluation.get('reason', '无')}\n"
            f"参考答案: {first_q_evaluation.get('correct_answer', '无')}\n"
            f"答案解释: {first_q_evaluation.get('explanation', '无')}"
        )


    # Determine navigation button visibility for the first question
    nav_prev_visible = False # First question has no previous
    nav_next_visible = len(questions) > 1 # Show next if more than 1 question
    nav_submit_visible = False # Already submitted

    return (state,
            gr.update(value=message_content, visible=True), # Show score message
            total_score, # Return total score (optional, maybe just for display)
            question_display, # Update question display for Q1
            user_answer_value, # Update answer field for Q1
            evaluation_display_text, # Update evaluation display for Q1
            gr.update(visible=nav_prev_visible), # Update prev button visibility
            gr.update(visible=nav_next_visible), # Update next button visibility
            gr.update(visible=nav_submit_visible)) # Update submit button visibility


# --- Build the Gradio Interface ---

with gr.Blocks() as demo:
    # Use gr.State to manage the application state across interactions
    state = gr.State(value=initial_state)

    # Message box for showing errors or notifications
    message_box = gr.Textbox(label="信息", visible=False, interactive=False)
    total_score_display = gr.Textbox(label="总得分", visible=False, interactive=False) # For exam score

    # --- Main Menu Block ---
    with gr.Column(visible=True) as main_menu_block:
        gr.Label("教学与考核系统", label="主菜单")
        btn_teaching = gr.Button("教学模式")
        btn_exam = gr.Button("考核模式")
        btn_history = gr.Button("查看聊天记录")
        btn_wrong_book = gr.Button("错题本")

    # --- Teaching Mode Block ---
    with gr.Column(visible=False) as teaching_mode_block:
        gr.Label("教学模式", label="当前模式")
        # Chatbot component to display conversation
        chatbot = gr.Chatbot(label="对话记录")
        # Input area
        with gr.Row():
            chat_input = gr.Textbox(label="你的消息", scale=4)
            btn_send = gr.Button("发送", scale=1)
        with gr.Row():
            btn_voice_input = gr.Button("语音输入", scale=1)
            # Hidden textbox to receive voice recognition results via polling
            voice_text_output = gr.Textbox(label="识别文本", visible=False, interactive=False)
            btn_return_teaching = gr.Button("返回主菜单", scale=1)

    # --- Exam Mode Block ---
    with gr.Column(visible=False) as exam_mode_block:
        gr.Label("考核模式", label="当前模式")
        exam_message = gr.Textbox(label="考试信息", visible=False, interactive=False) # Messages like "生成考题失败" or "考试已提交"
        question_index_display = gr.Textbox(label="题目进度", interactive=False)
        question_description_display = gr.Markdown(label="题目描述") # Use Markdown for formatting
        # Components for different question types (conditionally visible/used)
        choice_options = gr.Radio(label="请选择答案", choices=[], visible=False) # Choices will be set dynamically
        fill_in_input = gr.Textbox(label="请填写答案", visible=False)
        open_answer_input = gr.Textbox(label="请回答", visible=False, lines=5) # For short answer
        # Evaluation display after submission
        evaluation_display = gr.Markdown(label="评判结果", visible=True) # Always visible after submit
        # Navigation buttons
        with gr.Row() as exam_nav_buttons:
            btn_prev_question = gr.Button("上一题", visible=False)
            btn_next_question = gr.Button("下一题", visible=False)
            btn_submit_exam = gr.Button("提交", visible=False)
            btn_return_exam = gr.Button("返回主菜单")

    # --- Chat History List Block ---
    with gr.Column(visible=False) as history_list_block:
         gr.Label("聊天记录列表", label="当前模式")
         history_message = gr.Textbox(label="信息", visible=False, interactive=False)
         # Display history list. Using gr.DataFrame to show keys and previews.
         history_table = gr.DataFrame(
             headers=["对话ID", "第一句话预览"],
             datatype=["str", "str"],
             interactive=False
         )
         # Select a row to view detail (requires JavaScript or extra component logic)
         # For simplicity, let's add an input box to type the Dialog ID and a button
         with gr.Row():
             history_select_id_input = gr.Textbox(label="输入对话ID查看详情", scale=2)
             btn_view_history_detail = gr.Button("查看详情", scale=1)
             btn_delete_history = gr.Button("删除选定记录", scale=1, variant="stop")

         btn_return_history_list = gr.Button("返回主菜单")


    # --- Chat History Detail Block ---
    with gr.Column(visible=False) as history_detail_block:
         gr.Label("聊天记录详情", label="当前模式")
         history_detail_chatbot = gr.Chatbot(label="对话详情") # Reuse chatbot component
         with gr.Row():
             btn_continue_chat = gr.Button("继续对话")
             btn_back_to_history_list = gr.Button("返回列表")


    # --- Wrong Book Types Block ---
    with gr.Column(visible=False) as wrong_book_types_block:
         gr.Label("错题本", label="当前模式")
         wrong_types_message = gr.Textbox(label="信息", visible=False, interactive=False)
         btn_wrong_choice = gr.Button("选择题", visible=False) # Visible only if questions exist
         btn_wrong_fill = gr.Button("填空题", visible=False)   # Visible only if questions exist
         btn_wrong_open = gr.Button("简答题", visible=False)   # Visible only if questions exist
         with gr.Row():
            btn_clear_wrong_book = gr.Button("清空错题本", variant="stop")
            btn_return_wrong_types = gr.Button("返回主菜单")


    # --- Wrong Book List Block ---
    with gr.Column(visible=False) as wrong_book_list_block:
         wrong_list_label = gr.Label("错题列表", label="当前模式") # Label will be updated with type
         wrong_list_message = gr.Textbox(label="信息", visible=False, interactive=False)
         wrong_list_table = gr.DataFrame(
             headers=["Key", "题目预览"],
             datatype=["str", "str"],
             interactive=False
         )
         # Select a row to view detail
         with gr.Row():
             wrong_select_key_input = gr.Textbox(label="输入题目Key查看详情", scale=2)
             btn_view_wrong_detail = gr.Button("查看详情", scale=1)
             btn_delete_wrong_from_list = gr.Button("删除选定题目", scale=1, variant="stop") # Delete from list view

         btn_back_to_wrong_types = gr.Button("返回错题类型")


    # --- Wrong Book Detail Block ---
    with gr.Column(visible=False) as wrong_book_detail_block:
         gr.Label("错题详情", label="当前模式")
         wrong_detail_description = gr.Markdown(label="题目描述")
         wrong_detail_type = gr.Textbox(label="类型", interactive=False)
         wrong_detail_options = gr.Markdown(label="选项", visible=False) # Only for choice
         wrong_detail_user_answer = gr.Textbox(label="你的答案", interactive=False)
         wrong_detail_correct_answer = gr.Textbox(label="正确答案", interactive=False)
         wrong_detail_explanation = gr.Markdown(label="答案解释")
         with gr.Row():
             btn_delete_wrong_from_detail = gr.Button("删除此错题", variant="stop") # Delete from detail view
             btn_back_to_wrong_list = gr.Button("返回列表")


    # --- Event Handling Wiring ---

    # Main Menu Buttons
    btn_teaching.click(
        start_teaching_mode,
        inputs=[state],
        outputs=[state, chatbot, chat_input] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Update visibility
    ).then( # Use then to update visibility after state change
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


    btn_exam.click(
        start_exam_mode,
        inputs=[state],
        outputs=[state, question_description_display, question_index_display, choice_options, fill_in_input, open_answer_input, exam_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Initial outputs for exam + update visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block]
    ).then( # After showing the first question, determine nav button visibility
         get_exam_nav_buttons_visibility, inputs=[state], outputs=[btn_prev_question, btn_next_question, btn_submit_exam]
    )


    btn_history.click(
        view_chat_history_list,
        inputs=[state],
        outputs=[state, history_table] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, history_list, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


    btn_wrong_book.click(
        view_wrong_book_types,
        inputs=[state],
        outputs=[state, btn_wrong_choice, btn_wrong_fill, btn_wrong_open] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, type button visibility, block visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    # Return to Main Menu Buttons
    btn_return_teaching.click(
        return_to_main_menu,
        inputs=[state],
        outputs=[state, btn_voice_input] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, voice button label, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_return_exam.click(
        return_to_main_menu,
        inputs=[state],
        outputs=[state, btn_voice_input] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, voice button label, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_return_history_list.click(
        return_to_main_menu,
        inputs=[state],
        outputs=[state, btn_voice_input] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, voice button label, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_return_wrong_types.click(
        return_to_main_menu,
        inputs=[state],
        outputs=[state, btn_voice_input] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, voice button label, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    # Teaching Mode Interactions
    btn_send.click(
        send_message,
        inputs=[state, chat_input],
        outputs=[state, chatbot, chat_input, voice_text_output] # Update state, chatbot, clear input, clear voice text display
    )
    # Use .submit for text input to trigger send on Enter key
    chat_input.submit(
         send_message,
         inputs=[state, chat_input],
         outputs=[state, chatbot, chat_input, voice_text_output] # Update state, chatbot, clear input, clear voice text display
    )

    # Voice Input Polling (Requires a Polling Component or loop in Gradio)
    # Gradio doesn't have a built-in continuous poller for this exact use case easily.
    # A common pattern is to use an every() event on a dummy component or the block itself.
    # This can impact performance. Let's try a simpler pattern: clicking the button starts/stops,
    # and a background thread updates a queue, which a separate poll function checks.
    # The poll function needs to trigger a UI update.
    btn_voice_input.click(
        toggle_voice_input,
        inputs=[state],
        outputs=[state, btn_voice_input] # Update state and button label
    )

    # Polling for voice recognition results. This will check the queue periodically.
    # The interval should be small enough for responsiveness but not too small to overload.
    # This part is simplified; real-time streaming UI updates are complex in Gradio.
    demo.load(
        poll_voice_input,
        inputs=[state],
        outputs=[state, voice_text_output, chat_input, message_box], # Update state, recognized text display, maybe input box, maybe message box
        every=1 # Poll every 1 second
    )


    # Exam Mode Interactions
    # Navigation Buttons
    btn_prev_question.click(
        lambda s: show_question(s, s.get("current_question_index", 0) - 1),
        inputs=[state],
        outputs=[state, question_description_display, choice_options, fill_in_input, open_answer_input, evaluation_display, btn_prev_question, btn_next_question, btn_submit_exam, exam_message] # Outputs for show_question
    )

    btn_next_question.click(
        lambda s: show_question(s, s.get("current_question_index", 0) + 1),
        inputs=[state],
        outputs=[state, question_description_display, choice_options, fill_in_input, open_answer_input, evaluation_display, btn_prev_question, btn_next_question, btn_submit_exam, exam_message] # Outputs for show_question
    )

    # Saving answers (triggered by changing input fields)
    choice_options.change(
        save_answer,
        inputs=[state, choice_options],
        outputs=[state] # Just update state
    )
    fill_in_input.change(
        save_answer,
        inputs=[state, fill_in_input],
        outputs=[state] # Just update state
    )
    open_answer_input.change(
        save_answer,
        inputs=[state, open_answer_input],
        outputs=[state] # Just update state
    )


    btn_submit_exam.click(
        submit_exam,
        inputs=[state],
        outputs=[state, exam_message, total_score_display, question_description_display, choice_options, fill_in_input, open_answer_input, evaluation_display, btn_prev_question, btn_next_question, btn_submit_exam] # State, message, score, and update Q1 display+nav
    )


    # Chat History List Interactions
    btn_view_history_detail.click(
        view_chat_detail,
        inputs=[state, history_select_id_input],
        outputs=[state, history_detail_chatbot, history_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, chat, message, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_delete_history.click(
         delete_chat_record_action,
         inputs=[state, history_select_id_input], # Use the input box value as the key to delete
         outputs=[state, history_table, history_message] # Update state, refresh list table, show message
    )

    # Chat History Detail Interactions
    btn_continue_chat.click(
        continue_conversation_from_history,
        inputs=[state],
        outputs=[state, chatbot, chat_input] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, chatbot, input, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


    btn_back_to_history_list.click(
         view_chat_history_list, # Reload the history list
         inputs=[state],
         outputs=[state, history_table] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Outputs: state, history_list, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


    # Wrong Book Types Interactions
    btn_wrong_choice.click(
         lambda s: view_wrong_book_list(s, "选择"),
         inputs=[state],
         outputs=[state, wrong_list_table, wrong_types_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # State, list data, message, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_wrong_fill.click(
         lambda s: view_wrong_book_list(s, "填空"),
         inputs=[state],
         outputs=[state, wrong_list_table, wrong_types_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # State, list data, message, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_wrong_open.click(
         lambda s: view_wrong_book_list(s, "简答"),
         inputs=[state],
         outputs=[state, wrong_list_table, wrong_types_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # State, list data, message, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_clear_wrong_book.click(
        lambda s: (s, app_logic.clear_wrong_questions_file()), # Return state and message
        inputs=[state],
        outputs=[state, wrong_types_message]
    )

    # Wrong Book List Interactions
    btn_view_wrong_detail.click(
        view_wrong_book_detail,
        inputs=[state, wrong_select_key_input],
        outputs=[state, wrong_detail_description, wrong_detail_type, wrong_detail_options, wrong_detail_user_answer, wrong_detail_correct_answer, wrong_detail_explanation, wrong_list_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # State, detail data, message, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])

    btn_delete_wrong_from_list.click(
        delete_wrong_question_action,
        inputs=[state, wrong_select_key_input], # Use the input box value as the key to delete
        outputs=[state, wrong_list_table, wrong_list_message] # Update state, refresh list table, show message
    )

    btn_back_to_wrong_types.click(
        view_wrong_book_types, # Return to types view
        inputs=[state],
        outputs=[state, btn_wrong_choice, btn_wrong_fill, btn_wrong_open] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # State, type button visibility, block visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


    # Wrong Book Detail Interactions
    btn_delete_wrong_from_detail.click(
        delete_wrong_question_action, # Delete the currently viewed one
        inputs=[state], # The key is in state["current_wrong_key"]
        outputs=[state, wrong_list_table, wrong_list_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # Update state, refresh list, show message, visibility
    ).then( # After deleting, go back to the list view and update visibility
        # Need to call view_wrong_book_list with the stored type
        lambda s: view_wrong_book_list(s, s.get("current_wrong_type", "选择")),
        inputs=[state],
         outputs=[state, wrong_list_table, wrong_list_message]
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


    btn_back_to_wrong_list.click(
         # Need to call view_wrong_book_list with the stored type
         lambda s: view_wrong_book_list(s, s.get("current_wrong_type", "选择")),
         inputs=[state],
         outputs=[state, wrong_list_table, wrong_list_message] + [main_menu_block, teaching_mode_block, exam_mode_block, history_list_block, history_detail_block, wrong_book_types_block, wrong_book_list_block, wrong_book_detail_block] # State, list data, message, visibility
    ).then( # Update visibility
        get_main_menu_visibility, inputs=[state], outputs=[main_menu_block]
    ).then(get_teaching_mode_visibility, inputs=[state], outputs=[teaching_mode_block]
    ).then(get_exam_mode_visibility, inputs=[state], outputs=[exam_mode_block]
    ).then(get_history_list_visibility, inputs=[state], outputs=[history_list_block]
    ).then(get_history_detail_visibility, inputs=[state], outputs=[history_detail_block]
    ).then(get_wrong_book_types_visibility, inputs=[state], outputs=[wrong_book_types_block]
    ).then(get_wrong_book_list_visibility, inputs=[state], outputs=[wrong_book_list_block]
    ).then(get_wrong_book_detail_visibility, inputs=[state], outputs=[wrong_book_detail_block])


# Launch the Gradio app
demo.launch()
