
import logging
from typing import Optional
import websockets
import asyncio
from websockets.client import connect
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScheebaGeminiHandler:
    def __init__(self, prompt, bot_ids, connection_manager):
        self.api_key = "AIzaSyBUjH-PkLSZzyDxFXeTlTw9s8PaZq2nNPc"
        self.model = "gemini-2.0-flash-live-001"
        self.uri = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key={self.api_key}"
        self.gemini_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.model_speaking = False
        self._message_task: Optional[asyncio.Task] = None
        self.conversation_history = []
        self.current_chart_displayed = None  
        self.prompt = prompt
        self.bot_ids = bot_ids
        self.connection_manager = connection_manager
        
    
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
            
            logger.info("WebSocket connection established")

            
            setup_message = {
                "setup": {
                    "model": f"models/{self.model}",
                    "generationConfig": {
                        "temperature": 0.7,
                        "response_modalities": ["AUDIO"],
                        "speech_config": {
                        "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
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
                }
            }
            
            setup_json = json.dumps(setup_message)
            logger.debug(f"Sending setup message: {setup_json}")
            
            await self.gemini_ws.send(setup_json)
            logger.info("Setup message sent")
            
            setup_response = await asyncio.wait_for(self.gemini_ws.recv(), timeout=10)
            logger.info(f"Setup response received: {setup_response}")
            
            # Parse setup response to check for errors
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
            
            # Handle tool calls first
            if "toolCall" in response:
                logger.info("Tool call received from Gemini")
                await self._handle_tool_call(response["toolCall"])
                return
            
            # Check for audio data
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
                # Handle audio response
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
                            "speaking": True
                        })
                    
                    # Send audio data to UI
                    await self.connection_manager.send_to_all({
                        "type": "audio", 
                        "data": audio_data,
                        "bot_type": "lyra"
                    })
                    logger.debug("Sent audio data to UI")
                
                # Check for text response (for debugging)
                if "text" in part:
                    logger.info(f"Gemini text response: {part['text']}")
            
            if not audio_found:
                logger.warning("No audio data found in response")
            
            # Check if turn is complete
            if server_content.get("turnComplete"):
                logger.info("Turn complete")
                if hasattr(self, 'current_transcription') and self.current_transcription.strip():
                    print(self.current_transcription)
                    self.conversation_history.append({
                        "role": "model",
                        "content": self.current_transcription.strip(),
                        "type": "audio_response"
                    })
                await asyncio.sleep(0.5)
                self.current_transcription = ""
                self.model_speaking = False
                await self.connection_manager.send_to_all({
                    "type": "model_speaking", 
                    "speaking": False,
                    "bot_type": "lyra"
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
            
            last_5_messages = self.conversation_history[-6:-1]
            context_parts = []
            for msg in last_5_messages:
                if msg["type"] in ["text_input", "audio_response"]:
                    role_label = "User" if msg["role"] == "user" else "lyra AI"
                    context_parts.append(f"{role_label}: {msg['content']}")
            
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
