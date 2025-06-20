import os
import requests
import json
from typing import List, Dict, Optional, Union

class Qwen2VLClient:
    """
    A flexible client for Qwen/Qwen2.5-VL-7B-Instruct via vLLM's OpenAI‐compatible API.
    Now wraps image & text (or text-only) together in a single 'user' message.
    """

    def __init__(
        self,
        host: str = "http://localhost",
        port: int = 8001,
        model: str = "Qwen/Qwen2.5-VL-7B-Instruct",
        temperature: float = 0.7,
        timeout: float = 120.0,
    ):
        """
        Args:
            host: The hostname or IP where vLLM is listening (e.g. "http://localhost").
            port: The port that vLLM’s OpenAI-compatible API is bound to (e.g. 8001).
            model: The exact model string passed to vLLM (must match how you launched it).
            temperature: Sampling temperature for generation (default 0.7).
            timeout: Timeout (in seconds) for the HTTP request to return.
        """
        self.endpoint = f"{host}:{port}/v1/chat/completions"
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def _build_payload(
        self,
        question: Optional[str] = None,
        image_path: Optional[str] = None,
        system_prompt: str = "You are a helpful assistant.",
        extra_messages: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Construct the JSON body so that:
          • A single system message always appears first,
          • Then a single user message, whose `content` is EITHER:
              – A string (if only text),
              – A list of {"type": …} dicts (if image+text or any extra type‐based items),
          • You may also append any number of additional 'extra_messages' inside that same user.content array.

        Args:
            question: If provided, this becomes one {"type":"text","text":question} entry.
                      If None, we omit the 'text' entry entirely.
            image_path: If provided, this becomes one {"type":"image_url","image_url":{"url": …}} entry.
                        If None, we omit the 'image_url' entry.
            system_prompt: The text of the system message.
            extra_messages: A list of extra {"type": …} dicts to append inside the user.content array.
                            For example: [{"type":"text","text":"some RAG context"}, …].
                            NOTE: each dict in extra_messages must itself have a valid "type" key.

        Returns:
            A dict with keys "model", "messages", "temperature".
            The "messages" list will contain exactly two items:
              1) a system message
              2) a single user message whose content is either a string or a list of type‐dicts
        """
        # 1) Build the "system" message
        system_msg = {
            "role": "system",
            "content": system_prompt
        }

        # 2) Decide how to build the "user" message
        #    If BOTH image_path and question (and/or extra_messages) are provided,
        #    we’ll bundle them all into a single list under user.content.
        #    If ONLY question is provided (no image), we can send content as a plain string.
        #    If ONLY image is provided (no question), we put just the image dict into a list.

        user_content: Union[str, List[Dict]]

        # If we have an image, we always build a dict like {"type":"image_url", "image_url": {"url": "file://…"}}
        type_entries: List[Dict] = []
        if image_path is not None:
            abs_path = os.path.abspath(image_path)
            file_url = f"file://{abs_path}"
            type_entries.append({
                "type": "image_url",
                "image_url": {"url": file_url}
            })

        # If we have a question, we build a {"type":"text", "text": question} entry
        if question is not None:
            type_entries.append({
                "type": "text",
                "text": question
            })

        # Append any extra_messages (each must be a valid {"type": …} dict)
        if extra_messages:
            type_entries.extend(extra_messages)

        # Now decide how to set user_content:
        if image_path is None and question is not None and not extra_messages:
            # Case A: text-only, no image, no extra. Send content as a simple string.
            user_content = question

        else:
            # Case B: image+text, or text+extra, or image+extra, etc.
            # We already built type_entries. If question is None, but image exists, type_entries has just the image_dict.
            # If question & image both None but extra_messages exist, type_entries is just extra_messages.
            # Always wrap as a list:
            user_content = type_entries

        # 3) Build the single "user" message
        user_msg: Dict[str, Union[str, List[Dict]]] = {
            "role": "user",
            "content": user_content
        }

        # 4) Put them together
        messages = [system_msg, user_msg]

        payload: Dict[str, Union[str, float, List[Dict]]] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature
        }
        return payload

    def chat_completion(
        self,
        question: Optional[str] = None,
        image_path: Optional[str] = None,
        system_prompt: str = "You are a helpful assistant.",
        extra_messages: Optional[List[Dict]] = None,
    ) -> str:
        """
        Send either a text-only chat or an image+text chat to vLLM.

        Args:
            question: The user’s text question. If you want TEXT-ONLY, pass question and image_path=None.
                      If you want IMAGE+TEXT, pass both image_path and question.
                      If you want IMAGE-ONLY, pass image_path and question=None.
            image_path: Local path to the image file, or None if no image.
            system_prompt: The system message string.
            extra_messages: A list of additional {"type": …} dicts to append inside the user message.
                            All such dicts must have a valid "type" key (e.g. {"type":"text","text":"…"}).

        Returns:
            The assistant’s reply (content string). Raises RuntimeError on HTTP or schema errors.
        """
        body = self._build_payload(
            question=question,
            image_path=image_path,
            system_prompt=system_prompt,
            extra_messages=extra_messages
        )

        # 1) Send the request
        try:
            response = requests.post(
                self.endpoint,
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Could not connect to vLLM at {self.endpoint}: {e}")

        # 2) Check status code
        if response.status_code != 200:
            try:
                err = response.json()
            except ValueError:
                err = response.text
            raise RuntimeError(f"vLLM request failed ({response.status_code}): {err}")

        # 3) Parse the JSON reply
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected vLLM response format: {payload}") from e

        
def main():
    client = Qwen2VLClient(
        host="http://localhost",
        port=8001,
        model="Qwen/Qwen2.5-VL-7B-Instruct",
        temperature=0.7
    )

    # No image_path, only question
    # question = "Explain the key differences between SQL and NoSQL databases."
    # try:
    #     answer = client.chat_completion(
    #         question=question,
    #         image_path=None,              # No image in this call
    #         system_prompt="You are a helpful knowledge assistant."
    #     )
    #     print("Model’s Answer (text only):\n", answer)
    # except Exception as e:
    #     print("Error during text‐only inference:", e)

     # Path to your local image
    image_path = "/home/peseyes/Desktop/resumeRAG/resume_analyzer/images/tick1.jpg"
    question   = (
        "Describe the image. It is a skill check from a candidate in a resume. "
        "Tell me the strengths the candidate tick."
    )

    try:
        answer = client.chat_completion(
            question=question,
            image_path=image_path,
            system_prompt="You are a helpful assistant."
        )
        print("Model’s Answer (image + text):\n", answer)
    except Exception as e:
        print("Error during image+text inference:", e)


if __name__ == "__main__":
    main()
