import { getDocuments } from "./api.js";
window.onload = async () => {

    try {

        const data = await getDocuments();

        console.log(data);

    }

    catch(err){

        console.error(err);

        alert("Unable to load graph data.");

    }

};