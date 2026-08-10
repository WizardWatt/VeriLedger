const pipelineSteps = [
    "step-upload",
    "step-ocr",
    "step-forensic",
    "step-graph",
    "step-ai",
    "step-result"
];

function delay(ms){

    return new Promise(resolve=>setTimeout(resolve,ms));

}

export function resetPipeline(){

    pipelineSteps.forEach(id=>{

        const circle=document
            .getElementById(id)
            .querySelector(".step-circle");

        circle.className="step-circle waiting";

    });

}

export async function runPipeline(){

    for(const id of pipelineSteps){

        const circle=document
            .getElementById(id)
            .querySelector(".step-circle");

        circle.classList.remove("waiting");

        circle.classList.add("running");

        await delay(600);

        circle.classList.remove("running");

        circle.classList.add("done");

    }

}