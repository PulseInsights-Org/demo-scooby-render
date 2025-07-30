
import logging
from typing import Optional, List, Dict, Any
import websockets
import asyncio
from websockets.client import connect
import json
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScoobyGeminiHandler:
    def __init__(self, prompt, bot_ids, connection_manager, participants_list, conversation_history,pulse_initializer_callback=None):
        self.api_key = "AIzaSyBUjH-PkLSZzyDxFXeTlTw9s8PaZq2nNPc"
        self.model = "gemini-2.0-flash-live-001"
        self.uri = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={self.api_key}"
        self.gemini_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.model_speaking = False
        self._message_task: Optional[asyncio.Task] = None
        self.conversation_history = conversation_history
        self.current_chart_displayed = None  
        self.prompt = prompt
        self.bot_ids = bot_ids
        self.connection_manager = connection_manager
        self.participants_list = participants_list or []
        self.meeting_link = None
        self.other_handler = None 
        self.pulse_initializer_callback = pulse_initializer_callback
    
    def update_participants(self, participants_list: List[Dict[str, Any]]):
        self.participants_list = participants_list
        logger.info(f"Updated participants list in ScoobyGeminiHandler: {len(participants_list)} participants")
    
    def get_participants(self) -> List[Dict[str, Any]]:
        return self.participants_list
    
    def get_active_participants(self) -> List[Dict[str, Any]]:
        return [p for p in self.participants_list if p.get('status') == 'joined']
    
    def get_participants_declaration(self):
        return {
            "name": "get_current_participants",
            "description": "Gets all participants who have joined meeting. Includes names those who have joined and left.",
            "parameters": {}
        }
    
    def set_other_handler(self, other_handler):
        self.other_handler = other_handler
    
    def get_all_participants_declaration(self):
        return {
            "name": "get_all_joined_participants",
            "description": "Gets all participants who are in the meeting currently",
            "parameters": {}
        }
    
    
    async def add_pulse(self):
        recall_api_url = "https://us-west-2.recall.ai/api/v1/bot/"
        recall_api_key = "8487c64e0ef42223efb24178c870d178c2c494f5"
        webpage_url = "https://demo-scooby-render.onrender.com/pulse"
        bot_name = "Lyra"
        print(self.meeting_link)
        payload = {
            "meeting_url": self.meeting_link,
            "bot_name": bot_name,
            "recording_config": {
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": "https://demo-scooby-render.onrender.com/api/webhook/recall",
                        "events": ["transcript.data"]
                    }
                ],
                "transcript": {
                    "provider": {
                        "meeting_captions": {}
                    }
                }
            },
            "output_media": {
                "camera": { 
                    "kind": "webpage",
                    "config": {
                        "url": webpage_url
                    }
                }
            },
            "variant": {
                "zoom": "web_4_core",
                "google_meet": "web_4_core",
                "microsoft_teams": "web_4_core"
            }
        }
        
        headers = {
            "Authorization": recall_api_key,
            "accept": "application/json",
            "content-type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
                response = await client.post(
                    recall_api_url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                asyncio.sleep(45)
                if response.status_code in [200, 201]:
                    if self.pulse_initializer_callback:
                        await self.pulse_initializer_callback()
                    return {
                        "success": True,
                        "message": "Pulse AI bot successfully added to meeting",
                    }
                else:
                    error_detail = response.text
                    logger.error(f"Failed to add bot to meeting {self.meeting_link}: {error_detail}")
                    return {
                        "success": False,
                        "message": "Pulse AI bot was not successfully added to meeting",
                    }

    def get_add_bot_declaration(self):
        return {
            "name": "add_pulse_bot",
            "description": "Adds pulse AI to the current meeting",
            "parameters": {}
        }
    
    def update_meeting_link(self, meeting_link: str):
        self.meeting_link = meeting_link
        logger.info(f"Updated meeting link in ScoobyGeminiHandler: {meeting_link}")
              
    def get_conversation_history(self):
        return self.conversation_history
    
    def clear_conversation_history(self):
        self.conversation_history = []

    async def connect_to_gemini(self):
        """Connect to Gemini WebSocket with FAISS tool support"""
        logger.info("Starting connection to Gemini...")
        try:
            logger.info(f"Connecting to Gemini URI: {self.uri}")
            
            self.gemini_ws = await asyncio.wait_for(
                connect(
                    self.uri,
                    extra_headers={"Content-Type": "application/json"},
                    ping_interval=30,
                    ping_timeout=10
                ),
                timeout=10
            )
            
            all_participants_tool = self.get_all_participants_declaration()
            current_participants_tool = self.get_participants_declaration()
            add_bot_tool = self.get_add_bot_declaration()
            logger.info("WebSocket connection established")
        
            setup_message = {
                "setup": {
                    "model": f"models/{self.model}",
                    "generationConfig": {
                        "temperature": 0,
                        "response_modalities": ["AUDIO"],
                        "speech_config": {
                        "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}}
                    },
                    },
                    "output_audio_transcription": {},
                    "systemInstruction": {
                        "parts": [
                            {
                                "text": (
                                    self.prompt
                                )
                            }
                        ]
                    },
                    "tools": [
                        {
                            "functionDeclarations": [all_participants_tool, current_participants_tool]
                        }
                    ]
                }
            }
            
            setup_json = json.dumps(setup_message)
            logger.debug(f"Sending setup message: {setup_json}")
            
            await self.gemini_ws.send(setup_json)
            logger.info("Setup message sent")
            
            setup_response = await asyncio.wait_for(self.gemini_ws.recv(), timeout=10)
            logger.info(f"Setup response received: {setup_response}")
            
            try:
                setup_data = json.loads(setup_response)
                if "error" in setup_data:
                    logger.error(f"Setup error: {setup_data['error']}")
                    raise Exception(f"Setup error: {setup_data['error']}")
            except json.JSONDecodeError:
                logger.warning("Could not parse setup response as JSON")
            
            self.is_connected = True
            logger.info("Successfully connected to Gemini with company knowledge base tool support")
            
            # Start listening for messages
            self._message_task = asyncio.create_task(self._handle_gemini_messages())
            logger.info("Message handler task started")
            
        except asyncio.TimeoutError:
            logger.error("Timeout while connecting to Gemini")
            if self.gemini_ws:
                try:
                    await self.gemini_ws.close()
                except:
                    pass
                self.gemini_ws = None
            raise Exception("Timeout connecting to Gemini")
        except Exception as e:
            logger.error(f"Failed to connect to Gemini: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            if self.gemini_ws:
                try:
                    await self.gemini_ws.close()
                except:
                    pass
                self.gemini_ws = None
            raise
    
    async def _handle_tool_call(self, tool_call):
        try:
            function_responses = []
            
            for fc in tool_call.get("functionCalls", []):
                function_name = fc.get("name")
                function_args = fc.get("args", {})
                function_id = fc.get("id")
                
                logger.info(f"Function called: {function_name} with args: {function_args}")
                
                if function_name == "get_current_participants":
                    search_result = self.get_active_participants()
                
                elif function_name == "get_all_joined_participants":         
                    search_result = self.get_participants()  
                
                elif function_name == "add_pulse_bot":
                    try:
                        await self.add_pulse()
                        search_result = {
                            "status": "success",
                            "message": "Pulse AI added successfully"
                        }
                    except Exception as e:
                        logger.error(f"Error adding Pulse AI: {e}")
                        search_result = {
                            "status": "error",
                            "message": str(e)
                        }
                else:
                    logger.warning(f"Unknown function call: {function_name}")
                    search_result = {
                        "status": "error",
                        "message": f"Unknown function call: {function_name}"
                    }
                 
                function_responses.append({
                        "id": function_id,
                        "name": function_name,
                        "response": {"result" : search_result}
                    })
                    
            if function_responses:
                tool_response = {
                    "toolResponse": {
                        "functionResponses": function_responses
                    }
                }
                await self.gemini_ws.send(json.dumps(tool_response))
                logger.info("Tool response sent back to Gemini")
                
        except Exception as e:
            logger.error(f"Error handling tool call: {e}")
            import traceback
            
            
    async def _handle_gemini_messages(self):
        """Handle incoming messages from Gemini"""
        logger.info("Starting Gemini message handler")
        try:
            if not self.gemini_ws:
                logger.error("No Gemini WebSocket connection in message handler")
                return
                
            logger.info("Listening for Gemini messages...")
            async for msg in self.gemini_ws:
                try:
                    logger.debug(f"Received message from Gemini: {msg[:200]}...")
                    response = json.loads(msg)
                    logger.debug(f"Parsed Gemini response: {response}")
                    await self._process_gemini_response(response)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from Gemini: {e}")
                    logger.error(f"Raw message: {msg}")
                except Exception as e:
                    logger.error(f"Error processing Gemini message: {e}")
                    logger.error(f"Raw message: {msg}")
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"Gemini connection closed: {e}")
        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"Gemini connection closed with error: {e}")
        except Exception as e:
            logger.error(f"Error in Gemini message handler: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        finally:
            logger.info("Gemini message handler finished")
            self.is_connected = False
    

    async def _process_gemini_response(self, response):
        """Process individual Gemini response"""
        try:
            logger.debug(f"Processing Gemini response: {response}")

            if "toolCall" in response:
                logger.info("Tool call received from Gemini")
                await self._handle_tool_call(response["toolCall"]) 
                return
            
            server_content = response.get("serverContent", {})
            logger.debug(f"Server content: {server_content}")
            
            if "outputTranscription" in server_content:
                transcription = server_content["outputTranscription"]
                if "text" in transcription:
                    transcribed_text = transcription["text"]
                    logger.info(f"Gemini response transcription: '{transcribed_text}'")
                    
                    if not hasattr(self, 'current_transcription'):
                        self.current_transcription = ""
                    
                    self.current_transcription += transcribed_text
            
            model_turn = server_content.get("modelTurn", {})
            logger.debug(f"Model turn: {model_turn}")
            
            parts = model_turn.get("parts", [])
            logger.debug(f"Parts count: {len(parts)}")
            
            audio_found = False
            for i, part in enumerate(parts):
                logger.debug(f"Part {i}: {part}")
                inline_data = part.get("inlineData", {})
                if inline_data.get("mimeType") == "audio/pcm;rate=24000" and inline_data.get("data"):
                    audio_data = inline_data["data"]
                    audio_found = True
                    logger.info(f"Found audio data, length: {len(audio_data)}")
                    
                    if not self.model_speaking:
                        self.model_speaking = True
                        logger.info("Model started speaking")
                        await self.connection_manager.send_to_all({
                            "type": "model_speaking", 
                            "speaking": True,
                            "bot_type": "scooby"
                        })
                    
                    # Send audio data to UI
                    await self.connection_manager.send_to_all({
                        "type": "audio", 
                        "data": audio_data,
                        "bot_type": "scooby"
                    })
                    logger.debug("Sent audio data to UI")
                
                # Check for text response (for debugging)
                if "text" in part:
                    logger.info(f"Gemini text response: {part['text']}")
            
            if not audio_found:
                logger.warning("No audio data found in response")
        
            if server_content.get("turnComplete"):
                logger.info("Turn complete")
                if hasattr(self, 'current_transcription') and self.current_transcription.strip():
                    print(self.current_transcription)
                    self.conversation_history.append({
                        "role": "model",
                        "content": self.current_transcription.strip(),
                        "type": "audio_response"
                    })
                    transcription_lower = self.current_transcription.strip().lower()
                    if self.other_handler:
                        if "lyra" in transcription_lower:
                            logger.info("Pulse mentioned in Scooby transcription - sending to Pulse")
                            await asyncio.sleep(5)  
                            await self.other_handler.send_text_to_gemini(
                                f"Scooby said: {self.current_transcription.strip()}"
                            )
                await asyncio.sleep(0.5)
                self.current_transcription = ""
                self.model_speaking = False
                await self.connection_manager.send_to_all({
                    "type": "model_speaking", 
                    "speaking": False,
                    "bot_type": "scooby"
                })
                logger.info("Model stopped speaking")
                
        except Exception as e:
            logger.error(f"Error processing Gemini response: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            logger.error(f"Response that caused error: {response}")

    async def send_text_to_gemini(self, text: str):
        """Send text to Gemini for audio response"""
        logger.info(f"Attempting to send text to Gemini: {text}")
        
        if not self.is_connected:
            logger.warning("Not connected to Gemini, attempting to connect...")
            await self.connect_to_gemini()
        
        if not self.gemini_ws:
            logger.error("No Gemini WebSocket connection available")
            return
        
        if self.gemini_ws.closed:
            logger.error("Gemini WebSocket connection is closed")
            self.is_connected = False
            return
        
        if self.model_speaking:
            logger.info("Model is speaking, skipping text input")
            return
        
        try:
            self.conversation_history.append({
                "role": "user",
                "content": text,
                "type": "text_input"
            })
            
            last_5_messages = self.conversation_history[-9:-1]
            context_parts = []
            for msg in last_5_messages:
                if msg["type"] in ["text_input", "audio_response"]:
                    role_label = "User" if msg["role"] == "user" else "Scooby"
                    context_parts.append(f"{role_label}: {msg['content']}")
            
            # Create the full message with context
            if context_parts:
                context_string = "\n".join(context_parts)
                full_message = f"[Previous conversation context]:\n{context_string}\n\n[Current message]:\n{text}"
            else:
                full_message = text
            
            message = {
                "realtimeInput": {
                    "text": full_message
                }
            }
            
            message_json = json.dumps(message)
            logger.debug(f"Sending message to Gemini: {message_json}")
            
            await self.gemini_ws.send(message_json)
            logger.info(f"Successfully sent text to Gemini: {text}")
            
        except websockets.exceptions.ConnectionClosed as e:
            logger.error(f"Connection closed while sending text: {e}")
            self.is_connected = False
            raise
        except Exception as e:
            logger.error(f"Error sending text to Gemini: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.is_connected = False
            raise

    async def cleanup(self):
        """Close Gemini connection"""
        if self._message_task and not self._message_task.done():
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass
        
        if self.gemini_ws:
            try:
                await self.gemini_ws.close()
            except Exception as e:
                logger.error(f"Error closing Gemini connection: {e}")
            finally:
                self.gemini_ws = None
        self.is_connected = False
