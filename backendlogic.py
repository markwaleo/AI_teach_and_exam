import threading
import pyaudio
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
import openai
import json
import re
import os
import queue # Used for voice recognition result communication

# Initialize API keys
def get_key(filename='key.txt'):
    """
    Reads API keys from a file.
    Expects two lines: dashscope_key, openai_key
    """
    try:
        with open(filename, 'r') as file:
            lines = file.readlines()
            dashscope_key = lines[0].strip()
            openai_key = lines[1].strip()
        return dashscope_key, openai_key
    except FileNotFoundError:
        print(f"Error: {filename} not found. Please create it with your API keys.")
        return None, None
    except IndexError:
        print(f"Error: {filename} format incorrect. Expecting two lines.")
        return None, None
    except Exception as e:
        print(f"Error reading API keys: {e}")
        return None, None

# Initialize API keys globally for simplicity, but consider passing them in a real app
# These might need to be set *after* this module is imported in the Gradio app
# or managed within the AppLogic class if the keys are loaded dynamically.
# For now, keep them as in the original script:
dashscope_api_key, openai_api_key = get_key()
if dashscope_api_key:
    dashscope.api_key = dashscope_api_key
if openai_api_key:
    openai.api_key = openai_api_key
openai.api_base = "https://api.chatfire.cn/v1" # Assuming this base URL is still needed

# Global state for voice recognition thread communication
# In a Gradio app, this might be better managed within a class instance
# or using Gradio's State for a specific session.
# For now, let's use a queue for simplicity in backend.
voice_recognition_queue = queue.Queue()
voice_recognition_active = False
voice_recognition_thread = None

# Custom Callback class for ASR
class BackendRecognitionCallback(RecognitionCallback):
    """
    Callback class to process ASR results and put final sentences into a queue.
    """
    def __init__(self, result_queue):
        super().__init__()
        self.result_queue = result_queue # Queue to communicate with main thread

    def on_event(self, result: RecognitionResult) -> None:
        """
        Processes ASR result, puts final sentence into the queue.
        """
        try:
            sentence = result.get_sentence()
            if sentence and RecognitionResult.is_sentence_end(sentence):
                text = sentence.get("text", "")
                if text:
                    self.result_queue.put(text) # Put result into the queue
        except Exception as e:
            print(f"Error processing recognition result in callback: {e}")

def run_recognition(result_queue):
    """
    Starts the voice recognition thread.
    Reads audio data and sends to ASR.
    """
    global voice_recognition_active
    voice_recognition_active = True
    mic = None
    stream = None
    recognition = None

    try:
        mic = pyaudio.PyAudio()
        stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=3200)

        callback = BackendRecognitionCallback(result_queue)

        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="pcm",
            sample_rate=16000,
            callback=callback
        )
        recognition.start()

        print("Voice recognition started...")
        while voice_recognition_active:
            try:
                data = stream.read(3200, exception_on_overflow=False)
                recognition.send_audio_frame(data)
            except IOError as e:
                # Handle potential buffer overflow errors gracefully
                # print(f"Audio buffer error: {e}")
                continue # Skip this frame, keep reading

    except Exception as e:
        print(f"Voice recognition error: {e}")
        result_queue.put(f"[Error: {e}]") # Signal error to the main thread
    finally:
        print("Voice recognition stopping...")
        if recognition:
            recognition.stop()
        if stream:
            stream.stop_stream()
            stream.close()
        if mic:
            mic.terminate()
        voice_recognition_active = False
        result_queue.put("[STOPPED]") # Signal the thread has stopped

def start_voice_recognition_thread():
    """Starts the voice recognition in a separate thread."""
    global voice_recognition_thread, voice_recognition_active
    if not voice_recognition_active:
        # Clear the queue before starting
        while not voice_recognition_queue.empty():
            try:
                voice_recognition_queue.get_nowait()
            except queue.Empty:
                pass
        voice_recognition_thread = threading.Thread(target=run_recognition, args=(voice_recognition_queue,))
        voice_recognition_thread.daemon = True # Allow thread to exit with main program
        voice_recognition_thread.start()
        return "停止语音输入"
    return "语音输入 (已在运行)" # Should not happen if logic is correct

def stop_voice_recognition_thread():
    """Signals the voice recognition thread to stop."""
    global voice_recognition_active
    if voice_recognition_active:
        voice_recognition_active = False
        # Optional: Wait for the thread to finish if needed, but daemon=True handles exit.
        # if voice_recognition_thread and voice_recognition_thread.is_alive():
        #     voice_recognition_thread.join(timeout=5) # Wait up to 5 seconds
        return "语音输入"
    return "语音输入 (已停止)" # Should not happen if logic is correct

def get_voice_recognition_result():
    """Checks the queue for a voice recognition result."""
    try:
        # Get all available results from the queue
        results = []
        while not voice_recognition_queue.empty():
            results.append(voice_recognition_queue.get_nowait())
        if results:
             # Concatenate results, or just return the last final one
             # Assuming the queue gets final sentences, joining might work.
             # Or just return the most recent final sentence.
             # Let's return the last item, assuming it's the final sentence or stop signal.
            last_result = results[-1]
            if last_result == "[STOPPED]" or last_result.startswith("[Error:"):
                 return last_result # Signal thread state or error
            else:
                 return last_result # Return the recognized text
        return None # No new result
    except queue.Empty:
        return None # Queue is empty

# --- Core Logic Class (extracted from App) ---
class AppLogic:
    def __init__(self):
        self.chat_record_path = "discuss.json"
        self.wrong_question_path = "wrong.json"
        self.conversation_history = []
        self.user_answers = {}
        self.evaluation_results = {}
        self.current_dialog_key = None
        self.exam_questions = [] # Store generated exam questions

    def save_chat_history(self):
        """Saves current conversation history to a JSON file."""
        if not self.conversation_history:
            print("No conversation history to save.")
            return

        try:
            # Load existing records
            if os.path.exists(self.chat_record_path):
                with open(self.chat_record_path, "r", encoding="utf-8") as file:
                    existing_data = json.load(file)
            else:
                existing_data = {}

            # Determine dialog key
            if not self.current_dialog_key or self.current_dialog_key not in existing_data:
                 # Create new dialogue record if it's a new conversation or key doesn't exist
                 # Find the next available dialog key
                 dialog_num = 1
                 while f"dialog{dialog_num}" in existing_data:
                     dialog_num += 1
                 dialog_key = f"dialog{dialog_num}"
                 dialog_data = {"num": 0}
                 self.current_dialog_key = dialog_key
                 existing_data[dialog_key] = dialog_data
            else:
                 # Get current dialogue record
                 dialog_key = self.current_dialog_key
                 dialog_data = existing_data.get(dialog_key, {"num": 0}) # Should exist if key is in existing_data


            # Append current conversation content
            existing_num = dialog_data["num"]
            # Only save new entries not already in the loaded dialog_data
            # We assume conversation_history contains the full history
            # Let's find where the new entries start.
            # This part needs careful logic if you are *continuing* a loaded conversation.
            # A simpler approach is to overwrite the dialog with the current self.conversation_history
            # or carefully append only truly *new* entries.
            # Let's simplify: just save the current conversation_history under the key.
            # This means if you load a chat and add to it, saving will replace the old entry.
            # A more robust approach would track what's new.
            # For simplicity, let's just save the current state under the key.

            dialog_data_to_save = {"num": len(self.conversation_history) // 2} # Assuming Q, A pairs
            for i in range(len(self.conversation_history) // 2):
                # Ensure conversation_history structure is as expected
                if i * 2 < len(self.conversation_history) and self.conversation_history[i*2]["role"] == "user":
                     dialog_data_to_save[f"Q{i + 1}"] = self.conversation_history[i * 2]["content"]
                if i * 2 + 1 < len(self.conversation_history) and self.conversation_history[i*2 + 1]["role"] == "assistant":
                     dialog_data_to_save[f"A{i + 1}"] = self.conversation_history[i * 2 + 1]["content"]

            existing_data[dialog_key] = dialog_data_to_save


            # Save to file
            with open(self.chat_record_path, "w", encoding="utf-8") as file:
                json.dump(existing_data, file, ensure_ascii=False, indent=4)
            print(f"Chat history saved to {self.chat_record_path}")
            return "聊天记录已保存。"

        except Exception as e:
            print(f"Error saving chat history: {e}")
            return f"保存聊天记录出错: {e}"

    def load_chat_history_list(self):
        """Loads chat history list for display."""
        try:
            if os.path.exists(self.chat_record_path):
                with open(self.chat_record_path, "r", encoding="utf-8") as file:
                    chat_data = json.load(file)
                # Prepare data for display: list of (dialog_key, first_question_preview)
                history_list = []
                for dialog_key, dialog_content in chat_data.items():
                    first_question = dialog_content.get("Q1", "无提问内容")[:30] # Preview
                    history_list.append((dialog_key, first_question))
                return history_list, chat_data # Return list for display and full data for detail lookup
            else:
                return [], {} # No file, return empty list and data
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Error loading chat history list: {e}")
            return [], {} # Return empty on error

    def load_chat_detail(self, chat_data, dialog_key):
         """Loads detailed conversation for a given dialog key."""
         dialog = chat_data.get(dialog_key, {})
         if not dialog:
             return None, "未找到指定对话"

         # Convert dialog format (Q1, A1, Q2, A2...) to conversation_history list
         conversation = []
         for i in range(1, dialog.get("num", 0) + 1):
             if f"Q{i}" in dialog:
                 conversation.append({"role": "user", "content": dialog[f"Q{i}"]})
             if f"A{i}" in dialog:
                 conversation.append({"role": "assistant", "content": dialog[f"A{i}"]})

         self.current_dialog_key = dialog_key # Set current key if continuing
         self.conversation_history = conversation # Load history for continuation

         return conversation, None # Return conversation list and no error message

    def delete_chat_record(self, dialog_key):
        """Deletes a specific chat record."""
        try:
            if os.path.exists(self.chat_record_path):
                with open(self.chat_record_path, "r", encoding="utf-8") as file:
                    chat_data = json.load(file)
            else:
                return "聊天记录文件不存在。"

            if dialog_key in chat_data:
                del chat_data[dialog_key]

                with open(self.chat_record_path, "w", encoding="utf-8") as file:
                    json.dump(chat_data, file, ensure_ascii=False, indent=4)
                return f"聊天记录 '{dialog_key}' 已删除。"
            else:
                return f"未找到指定聊天记录 '{dialog_key}'。"
        except Exception as e:
            print(f"Error deleting chat record: {e}")
            return f"删除聊天记录时出错: {e}"


    def save_wrong_questions(self):
        """Saves accumulated wrong questions to a JSON file."""
        if not self.evaluation_results:
            print("No evaluation results to save wrong questions from.")
            return

        try:
            if os.path.exists(self.wrong_question_path):
                with open(self.wrong_question_path, "r", encoding="utf-8") as file:
                    existing_data = json.load(file)
            else:
                existing_data = {}

            # Determine starting index for new questions
            # Find the max key (assuming keys are strings of integers)
            next_key_num = 1
            if existing_data:
                 try:
                     max_key = max(int(k) for k in existing_data.keys())
                     next_key_num = max_key + 1
                 except ValueError:
                     # Handle cases where keys are not integers or file is empty but not {}
                     pass # Start from 1

            new_wrong_count = 0
            for index, evaluation in self.evaluation_results.items():
                # Ensure index is valid for exam_questions list
                if 0 <= index < len(self.exam_questions):
                    question = self.exam_questions[index]
                    # Check if the question result indicates it was wrong or partially correct
                    # In original, it was only != "正确". Let's keep that logic.
                    if evaluation.get("result") != "正确":
                        # Check if this question (by description+type) might already be in wrong book
                        # Simple check by description preview - might not be robust
                        is_duplicate = False
                        current_q_desc = question["description"]
                        for existing_q in existing_data.values():
                            if existing_q.get("description") == current_q_desc and existing_q.get("type") == question["type"]:
                                # Found a potential duplicate based on description and type
                                is_duplicate = True
                                break # Stop checking existing entries for this question

                        if not is_duplicate:
                            existing_data[str(next_key_num)] = {
                                "type": question["type"],
                                "description": question["description"],
                                "options": question.get("option", ""),
                                "answer": question["answer"],
                                "user_answer": self.user_answers.get(index, ""),
                                "explanation": question.get("explanation", "") # Save explanation from evaluation if available
                            }
                            next_key_num += 1
                            new_wrong_count += 1
                        else:
                             print(f"Skipping saving potential duplicate wrong question: {question['description'][:20]}...")


            if new_wrong_count > 0:
                with open(self.wrong_question_path, "w", encoding="utf-8") as file:
                    json.dump(existing_data, file, ensure_ascii=False, indent=4)
                print(f"Saved {new_wrong_count} new wrong questions to {self.wrong_question_path}")
                return f"已保存 {new_wrong_count} 道错题。"
            else:
                 print("No new wrong questions to save.")
                 return "没有新的错题需要保存。"


        except Exception as e:
            print(f"Error saving wrong questions: {e}")
            return f"保存错题时出错: {e}"


    def load_wrong_questions(self):
        """Loads all wrong questions from the JSON file."""
        try:
            if os.path.exists(self.wrong_question_path):
                with open(self.wrong_question_path, "r", encoding="utf-8") as file:
                    wrong_data = json.load(file)
                return wrong_data, None # Return data and no error
            else:
                return {}, "错题本文件不存在。" # No file, return empty data and message
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Error loading wrong questions: {e}")
            return {}, f"加载错题本出错: {e}" # Return empty on error


    def load_wrong_questions_by_type(self, question_type):
        """Loads wrong questions filtered by type."""
        wrong_data, error = self.load_wrong_questions()
        if error:
            return {}, error # Return empty and error if loading failed

        filtered_questions = {
            key: question for key, question in wrong_data.items() if question.get("type") == question_type
        }
        return filtered_questions, None # Return filtered data and no error


    def delete_wrong_question(self, question_key):
        """Deletes a specific wrong question by key."""
        try:
            wrong_data, error = self.load_wrong_questions()
            if error:
                return error # Return error if loading failed

            if question_key in wrong_data:
                del wrong_data[question_key]

                with open(self.wrong_question_path, "w", encoding="utf-8") as file:
                    json.dump(wrong_data, file, ensure_ascii=False, indent=4)
                return f"错题 '{question_key}' 已删除。"
            else:
                return f"未找到指定错题 '{question_key}'。"
        except Exception as e:
            print(f"Error deleting wrong question: {e}")
            return f"删除错题时出错: {e}"

    def clear_wrong_questions_file(self):
        """Deletes the wrong questions file."""
        if os.path.exists(self.wrong_question_path):
            os.remove(self.wrong_question_path)
            return "错题本已清空。"
        return "错题本文件不存在，无需清空。"

    def generate_exam_questions(self):
        """Generates exam questions using OpenAI API."""
        print("Generating exam questions...")
        prompt = (
            "请生成10道关于测试技术与传感器的题目，题目请不要过于简单，比如不要出类似于啥传感器能检测压力（压力传感器）之类的问题，即看题干就能出答案的，每道题目格式如下："
            "{type='', description='', option='', answer='', explanation=''}。"
            "其中包含4个选择题，4个填空题和2个简答题。"
            "请确保题目内容明确、精确，避免多义性。"
            "对于可能有多种答案的题目，请在题干中明确要求回答其中的一种，或指定特定的方向。"
            "type为选择、填空、简答三选一，description为题目的描述，"
            "option为选择题的四个选项格式为A:xxx，B:...，C:...，D:...，"
            "填空和简答回复None即可，answer为题目的答案，选择题给出正确的选项（A-D），"
            "填空题给出要填的答案，简答题给出答案，explanation为答案的解释。\n"
            "请按以下格式一道一道地显示题目：\n"
            "{type=\"选择\", description=\"1+1=？\", option=\"A:1,B:2,C:3,D:4\", answer=\"B\", explanation=\"略\"}\n"
            "{type=\"填空\", description=\"古诗补全：床前明月光，_______地上霜。\", option=\"None\", answer=\"疑是\", explanation=\"略\"}\n"
            "{type=\"简答\", description=\"请说一说为什么压电晶体一压就会产生电？\", option=\"None\", answer=\"因为...\", explanation=\"略\"}"
        )
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": prompt}]
            )
            content = response['choices'][0]['message']['content']
            print("Raw AI response for questions:", content)

            # Parse the content string into a list of question dictionaries
            formatted_content = re.sub(r'(\w+)=', r'"\1":', content) # Convert key=value to "key":value
            # Handle potential trailing commas or extra characters outside {}
            json_objects_str = ",".join(re.findall(r'(\{.*?\}),?', formatted_content, re.DOTALL))
            json_array_str = f"[{json_objects_str}]"

            # Attempt to parse as a JSON array
            questions_list = json.loads(json_array_str)

            # Basic validation for the number of questions
            if len(questions_list) != 10:
                print(f"Warning: Generated {len(questions_list)} questions instead of 10.")

            # Basic validation for required keys in each question
            valid_questions = []
            required_keys = ["type", "description", "answer", "explanation"] # 'option' is optional for non-choice
            for q in questions_list:
                if all(key in q for key in required_keys) and q.get("type") in ["选择", "填空", "简答"]:
                     # Additional check for 'option' in '选择' type
                     if q["type"] == "选择" and "option" not in q:
                          print(f"Skipping choice question due to missing 'option': {q.get('description', 'N/A')[:30]}...")
                          continue
                     valid_questions.append(q)
                else:
                     print(f"Skipping invalid question format: {q}")


            self.exam_questions = valid_questions
            self.user_answers = {} # Reset user answers for a new exam
            self.evaluation_results = {} # Reset evaluation results
            print(f"Generated and parsed {len(self.exam_questions)} valid questions.")
            return self.exam_questions, None # Return questions list and no error

        except Exception as e:
            print(f"Error generating or parsing exam questions: {e}")
            self.exam_questions = []
            return [], f"生成考题时出错: {e}" # Return empty list and error message


    def submit_exam(self):
        """Evaluates user answers and calculates total score."""
        total_score = 0
        self.evaluation_results = {} # Clear previous results

        if not self.exam_questions:
            return 0, {}, "没有题目可以提交。"

        for index, question in enumerate(self.exam_questions):
            question_type = question.get('type', '未知')
            description = question.get('description', '无描述')
            correct_answer = question.get('answer', '').strip()
            user_answer = self.user_answers.get(index, "").strip()

            evaluation = {
                'result': '未作答', # Default
                'score': 0,
                'reason': '未作答',
                'correct_answer': correct_answer,
                'explanation': question.get('explanation', '')
            }

            if question_type == "选择":
                if user_answer == correct_answer:
                    evaluation['result'] = "正确"
                    evaluation['score'] = 10 # Assuming 10 points per question
                    evaluation['reason'] = '回答正确'
                else:
                    evaluation['result'] = "错误"
                    evaluation['score'] = 0
                    evaluation['reason'] = f'回答错误，正确答案是 {correct_answer}' # Provide correct answer
            elif question_type in ["填空", "简答"]:
                 # Use GPT for evaluation for fill-in and short answer
                 try:
                     evaluation_text = self.check_answer_with_gpt(question, user_answer)
                     parsed_evaluation = self.parse_evaluation(evaluation_text)
                     evaluation['score'] = parsed_evaluation.get('score', 0)
                     evaluation['reason'] = parsed_evaluation.get('reason', '无法解析评分理由')

                     # Determine result based on score for fill-in/short-answer
                     if evaluation['score'] == 10:
                         evaluation['result'] = '正确'
                     elif evaluation['score'] > 0:
                         evaluation['result'] = '部分正确'
                     else:
                         evaluation['result'] = '错误'

                 except Exception as e:
                     print(f"Error during GPT evaluation for question {index}: {e}")
                     evaluation['result'] = '评估失败'
                     evaluation['score'] = 0
                     evaluation['reason'] = f'GPT 评估出错: {e}'


            total_score += evaluation['score']
            self.evaluation_results[index] = evaluation

        print(f"Exam submitted. Total score: {total_score}")
        return total_score, self.evaluation_results, None # Return total score, results, and no error


    def check_answer_with_gpt(self, question, user_answer):
        """Uses GPT to evaluate non-multiple-choice answers."""
        prompt = (
            "你将扮演一位严格但公平的阅卷老师，"
            "请根据以下的标准答案和评分标准，评估用户的回答。"
            "满分为10分，请给出得分和简短的评分理由。"
            "如果用户的答案部分正确，也应给予适当的分数。"
            "请注意，答案不需要和标准答案一模一样，只要内容合理、正确即可得分。"
            "但如果用户未作答或答案与题目无关，则得0分。"
            "用户答案后面的内容才是用户的答案，也就是你要测评的内容"
            "请严格按照格式{{score=数字, reason=\"理由\"}}返回，不要有多余的内容。"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"问题：{question.get('description', 'N/A')}\n参考答案: {question.get('answer', 'N/A')}\n用户答案：{user_answer}"}
        ]
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=messages
            )
            return response['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error calling OpenAI for evaluation: {e}")
            return f"{{score=0, reason=\"API 调用失败: {e}\"}}" # Return a structured error response

    def parse_evaluation(self, evaluation_text):
        """Parses GPT's evaluation string into a dictionary."""
        try:
            # Attempt to parse as JSON first, if it's close to JSON format
            # Sometimes GPT might output valid JSON.
            try:
                # Replace common non-JSON friendly patterns like key=value
                evaluation_text_json_friendly = evaluation_text.strip()
                if evaluation_text_json_friendly.startswith('{') and evaluation_text_json_friendly.endswith('}'):
                    # Convert key=value to "key":value
                    evaluation_text_json_friendly = re.sub(r'(\w+)\s*=\s*', r'"\1": ', evaluation_text_json_friendly)
                    # Convert single quotes to double quotes for string values if necessary (be cautious)
                    # Simple attempt:
                    evaluation_text_json_friendly = re.sub(r"'([^']*)'", r'"\1"', evaluation_text_json_friendly)

                    # Attempt JSON load
                    eval_data = json.loads(evaluation_text_json_friendly)
                    if 'score' in eval_data and 'reason' in eval_data:
                         # Ensure score is integer
                         eval_data['score'] = int(eval_data['score'])
                         return eval_data # Successfully parsed as JSON-like
                    # If it loaded but didn't have expected keys, fall through to regex

            except (json.JSONDecodeError, ValueError):
                 # Not strict JSON, fall through to regex
                 pass


            # Fallback to regex parsing if JSON parsing failed
            # Matches { score: <digits>, reason: "<anything>" }
            pattern = r'\{\s*score\s*:\s*(\d+)\s*,\s*reason\s*:\s*"([^"]*)"\s*\}'
            match = re.search(pattern, evaluation_text)

            if match:
                score = int(match.group(1))
                reason = match.group(2)
                return {'score': score, 'reason': reason}
            else:
                print(f"Warning: Could not parse evaluation text with regex: {evaluation_text}")
                # Attempt a more general pattern if the strict one fails
                pattern_fallback = r'score.*?(\d+).*?reason.*?"?([^"]*)"?'
                match_fallback = re.search(pattern_fallback, evaluation_text, re.DOTALL | re.IGNORECASE)
                if match_fallback:
                    try:
                        score = int(match_fallback.group(1))
                        reason = match_fallback.group(2).strip()
                        print(f"Info: Parsed evaluation with fallback regex. Score: {score}, Reason: {reason[:50]}...")
                        return {'score': score, 'reason': reason}
                    except (ValueError, IndexError):
                         print(f"Warning: Fallback regex failed to parse score or reason.")
                         return {'score': 0, 'reason': f'无法完全解析评分结果: {evaluation_text}'}
                else:
                    print(f"Warning: Fallback regex also failed to parse evaluation text: {evaluation_text}")
                    return {'score': 0, 'reason': f'无法解析评分结果: {evaluation_text}'} # Final fallback


        except Exception as e:
            print(f"Severe error during evaluation parsing: {e}")
            return {'score': 0, 'reason': f'解析评分结果时发生严重错误: {e}'}

    # Methods to reset state for new interactions
    def reset_teaching_state(self):
         self.conversation_history = []
         self.current_dialog_key = None
         return "新的教学会话已开始。"

    def reset_exam_state(self):
         self.user_answers = {}
         self.evaluation_results = {}
         self.exam_questions = [] # Clear questions too
         return "考试状态已重置。"


# Instantiate the logic class
# logic = AppLogic() # This will be instantiated in the Gradio app instead
