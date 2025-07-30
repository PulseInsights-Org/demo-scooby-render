import logging
import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import  Set
from prompt import pulseAI_prompt, scoobyAI_prompt
from connection_manager import ConnectionManager
import os
import uvicorn

active_bot_ids: Set[str] = set()
connection_manager = ConnectionManager()
sheeba_gemini_handler = None
scooby_gemini_handler = None
participants = []
meeting_link = None
conversation_history = []

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

app = FastAPI()

origins = [
    "https://demo-scooby-render.onrender.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AddBotRequest(BaseModel):
    meeting_url: str
    bot_type: str

class RemoveBotRequest(BaseModel):
    bot_id: str

@app.get("/")
async def get_homepage():
    logger.info("Serving homepage - using pre-loaded knowledge base")
    return FileResponse("index.html")

@app.get("/pulse")
async def get_pulse_page():
    return FileResponse("pulse.html")

@app.get("/scooby") 
async def get_scooby_page():
    return FileResponse("scooby.html")

@app.get("/add_bot")
async def get_add_bot_page():
    logger.info("Serving add_bot page - using pre-loaded knowledge base")
    return FileResponse("add_bot.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for UI communication"""
    await websocket.accept()
    connection_id = f"ws_{id(websocket)}"
    connection_manager.add_connection(connection_id, websocket)
    
    try:
        await websocket.send_json({
            "type": "status",
            "connected": scooby_gemini_handler.is_connected,
            "bot_type": "both"
        })
        
        while True:
            data = await websocket.receive_text()
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket {connection_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}")
    finally:
        connection_manager.remove_connection(connection_id)

@app.post("/start")
async def start_meet():
    try:
        await scooby_gemini_handler.send_text_to_gemini(
                f"Speaker said: Start the meeting scooby"
            )
        logger.info("Successfully sent text to Gemini")
                    
    except Exception as e:
            logger.error(f"Error sending to Gemini: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
          
    
@app.post("/add_bots")
async def add_bot(request: AddBotRequest):
    global meeting_link
    meeting_link = request.meeting_url
    if scooby_gemini_handler:
        scooby_gemini_handler.update_meeting_link(meeting_link)
    logger.info("Adding bot to meeting - using pre-loaded knowledge base")
    
    recall_api_url = "https://us-west-2.recall.ai/api/v1/bot/"
    recall_api_key = "8487c64e0ef42223efb24178c870d178c2c494f5"

    if request.bot_type == "pulse":
        webpage_url = "https://demo-scooby-render.onrender.com/pulse"
        bot_name = "lyra"
    elif request.bot_type == "scooby":
        webpage_url = "https://demo-scooby-render.onrender.com/scooby"
        bot_name = "Scooby"
    else:
        raise HTTPException(status_code=400, detail="Invalid bot_type. Use 'pulse' or 'scooby'")
    
    
    payload = {
        "meeting_url": request.meeting_url,
        "bot_name": bot_name,
        "recording_config": {
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": "https://demo-scooby-render.onrender.com/api/webhook/recall",
                    "events": ["transcript.data","participant_events.join"]
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
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                recall_api_url,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code in [200, 201]:
                bot_data = response.json()
                bot_id = bot_data.get("id")
                
                if bot_id:
                    active_bot_ids.add(bot_id)
                    logger.info(f"Bot ID {bot_id} added to active bots. Total active bots: {len(active_bot_ids)}")
                    logger.info(f"Active bot IDs: {list(active_bot_ids)}")
                
                logger.info(f"Successfully added bot to meeting: {request.meeting_url}")
                return {
                    "success": True,
                    "message": "Pulse AI bot successfully added to meeting",
                    "bot_id": bot_id,
                    "bot_data": bot_data,
                    "active_bots_count": len(active_bot_ids)
                }
            else:
                error_detail = response.text
                logger.error(f"Failed to add bot to meeting {request.meeting_url}: {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to add Pulse AI bot to meeting: {error_detail}"
                )
                
    except httpx.TimeoutException:
        logger.error(f"Timeout adding bot to meeting: {request.meeting_url}")
        raise HTTPException(status_code=408, detail="Request timeout")
    except Exception as e:
        logger.error(f"Error adding bot to meeting {request.meeting_url}: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/remove_bot")
async def remove_bot(request: RemoveBotRequest):
    recall_api_url = f"https://us-west-2.recall.ai/api/v1/bot/{request.bot_id}/leave_call/"
    recall_api_key = "8487c64e0ef42223efb24178c870d178c2c494f5"
    
    headers = {
        "Authorization": recall_api_key,
        "accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                recall_api_url,
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code in [200, 201]:
                bot_data = response.json()
                
                if request.bot_id in active_bot_ids:
                    active_bot_ids.remove(request.bot_id)
                    logger.info(f"Bot ID {request.bot_id} removed from active bots. Total active bots: {len(active_bot_ids)}")
                    logger.info(f"Active bot IDs: {list(active_bot_ids)}")
                
                logger.info(f"Successfully removed bot {request.bot_id} from meeting")
                return {
                    "success": True,
                    "message": "Pulse AI bot successfully removed from meeting",
                    "bot_id": request.bot_id,
                    "response_data": bot_data,
                    "active_bots_count": len(active_bot_ids)
                }
            else:
                error_detail = response.text
                logger.error(f"Failed to remove bot {request.bot_id} from meeting: {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to remove Pulse AI bot from meeting: {error_detail}"
                )
                
    except httpx.TimeoutException:
        logger.error(f"Timeout removing bot {request.bot_id} from meeting")
        raise HTTPException(status_code=408, detail="Request timeout")
    except Exception as e:
        logger.error(f"Error removing bot {request.bot_id} from meeting: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
    
def add_participant(participant_data):

    participant_id = participant_data.get('id')
    participant_name = participant_data.get('name')
    
    existing_participant = next((p for p in participants if p['id'] == participant_id), None)
    
    if not existing_participant:

        participants.append({
            'id': participant_id,
            'name': participant_name,
            'is_host': participant_data.get('is_host', False),
            'platform': participant_data.get('platform', 'unknown'),
            'extra_data': participant_data.get('extra_data', {}),
            'status': 'joined'
        })
        logger.info(f"Added new participant: {participant_name} (ID: {participant_id})")
        if scooby_gemini_handler:
            scooby_gemini_handler.update_participants(participants)
    else:
        existing_participant.update({
            'name': participant_name,
            'is_host': participant_data.get('is_host', False),
            'platform': participant_data.get('platform', 'unknown'),
            'extra_data': participant_data.get('extra_data', {}),
            'status': 'joined'
        })
        logger.info(f"Updated participant: {participant_name} (ID: {participant_id})")

def get_participant_by_id(participant_id):
    return next((p for p in participants if p['id'] == participant_id), None)
        
@app.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    logger.info("Received webhook from Recall.ai")
    try:
        payload = await request.json()
        logger.debug(f"Webhook payload: {payload}")
        print(payload)
        
        event_type = payload.get("event")
        
        if event_type == "transcript.data":
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]

            spoken_text = " ".join([w["text"] for w in words])
            logger.info(f"Transcribed text from {speaker}: {spoken_text}")
            
            is_pulse_speaking = speaker and "scheeba" in speaker.lower()
            is_scooby_speaking = speaker and "scooby" in speaker.lower()
            
            if sheeba_gemini_handler:
                if "lyra" in spoken_text.lower():
                    logger.info(f"lyra mentioned by {speaker}: {spoken_text}")
                    if is_scooby_speaking:
                        logger.info("Scooby mentioned lyra - adding 2 second delay before responding")
                        pass
                    
                    logger.info(f"Gemini connection status - Connected: {sheeba_gemini_handler.is_connected}, WS: {sheeba_gemini_handler.gemini_ws is not None}")
                    
                    try:
                        await sheeba_gemini_handler.send_text_to_gemini(
                            f"Speaker {speaker} said: {spoken_text}"
                        )
                        logger.info("Successfully sent text to Gemini")
                        
                    except Exception as e:
                        logger.error(f"Error sending to Gemini: {e}")
                        import traceback
                        logger.error(f"Traceback: {traceback.format_exc()}")
            
            if "scooby" in spoken_text.lower():
                logger.info(f"Scooby mentioned by {speaker}: {spoken_text}")
                
                logger.info(f"Gemini connection status - Connected: {scooby_gemini_handler.is_connected}, WS: {scooby_gemini_handler.gemini_ws is not None}")
                if is_pulse_speaking:
                    logger.info("lyra mentioned Scooby - adding 2 second delay before responding")
                    pass
                try:
                    await scooby_gemini_handler.send_text_to_gemini(
                        f"Speaker {speaker} said: {spoken_text}"
                    )
                    logger.info("Successfully sent text to Gemini")
                    
                except Exception as e:
                    logger.error(f"Error sending to Gemini: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
            else:
                logger.debug(f"Pulse/scooby not mentioned in: {spoken_text}")
        
        elif event_type == "participant_events.join":
            participant_data = payload["data"]["data"]["participant"]
            action = payload["data"]["data"]["action"]
            
            if action == "join":
                add_participant(participant_data)
                logger.info(f"Participant joined: {participant_data['name']}")
                
                logger.info(f"Total participants: {len(participants)}")
                for p in participants:
                    logger.info(f"  - {p['name']} (ID: {p['id']}, Host: {p['is_host']})")
        
        elif event_type == "participant_events.leave":
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            
            participant = get_participant_by_id(participant_id)
            if participant:
                participant['status'] = 'left'
                logger.info(f"Participant left: {participant['name']}")
        
        else:
            logger.info(f"Received unhandled event type: {event_type}")

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

    return {"status": "ok"}


async def initialize_pulse_handler():
    global sheeba_gemini_handler
    if sheeba_gemini_handler is None:
        from SheebaAI_bot import ScheebaGeminiHandler
        sheeba_gemini_handler = ScheebaGeminiHandler(
            pulseAI_prompt, 
            active_bot_ids, 
            connection_manager 
        )
        
        scooby_gemini_handler.set_other_handler(sheeba_gemini_handler)
        
        await sheeba_gemini_handler.connect_to_gemini()
        logger.info("Pulse Gemini handler initialized and connected")
    
    return sheeba_gemini_handler

@app.on_event("startup")
async def startup_event():
    global sheeba_gemini_handler, scooby_gemini_handler, conversation_history
    try:
        
        from scoobyAI_bot import ScoobyGeminiHandler
        
        scooby_gemini_handler = ScoobyGeminiHandler(scoobyAI_prompt, 
                                                    active_bot_ids, 
                                                    connection_manager,
                                                    participants,
                                                    conversation_history,
                                                    initialize_pulse_handler)
        
        logger.info("Initializing Gemini connection on startup...")
        await scooby_gemini_handler.connect_to_gemini()
        logger.info("Gemini handler initialized successfully")
        
        logger.info("All services initialized successfully on startup")
        
    except Exception as e:
        logger.error(f"Failed to initialize services on startup: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on server shutdown"""
    logger.info("Shutting down server...")
    if sheeba_gemini_handler:
        await sheeba_gemini_handler.cleanup()
    await scooby_gemini_handler.cleanup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000)) 
    uvicorn.run(app, host="0.0.0.0", port=port)
