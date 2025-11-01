import os
from dotenv import load_dotenv
from graph.workflow import graph
from utils.logger import logger


def save_langgraph_visualization():
    """
    Generates and saves the LangGraph workflow diagram in mermaid and PNG formats.
    The diagram visualizes the true workflow including the orchestrator & loops.
    """
    logger.info("Generating LangGraph workflow visualization...")
    try:
        # Generate mermaid diagram text
        mermaid_diagram = graph.get_graph().draw_mermaid()
        
        # Save mermaid file
        with open("langgraph_workflow.mmd", "w", encoding="utf-8") as f:
            f.write(mermaid_diagram)
        logger.info("Mermaid workflow diagram saved as langgraph_workflow.mmd")
        print("Mermaid diagram saved as langgraph_workflow.mmd - you can view it at https://mermaid.live/")
        
        # Try to generate PNG
        try:
            png_data = graph.get_graph().draw_mermaid_png()
            with open("langgraph_workflow.png", "wb") as f:
                f.write(png_data)
            logger.info("PNG workflow diagram saved as langgraph_workflow.png")
            print("PNG workflow diagram saved as langgraph_workflow.png")
        except Exception as e:
            logger.warning(f"Failed to generate PNG diagram: {e}")
            print("Warning: PNG generation failed. Make sure you have graphviz installed for PNG output.")
            print("You can view the Mermaid diagram online at https://mermaid.live/")
        
    except Exception as err:
        logger.error(f"Error generating workflow visualization: {err}")
        print("Failed to generate LangGraph visualization:", err)


if __name__ == "__main__":
    load_dotenv()
    save_langgraph_visualization()
