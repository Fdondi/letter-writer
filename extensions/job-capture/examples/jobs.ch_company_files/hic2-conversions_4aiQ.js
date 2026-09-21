!function i() {
    if ((new URL(location.href)).searchParams.get("hic_jid")) {
        // set hic conv params:
        localStorage.setItem("hic_conv_params", location.href.split("?")[1]);
        try {
            let request = new XMLHttpRequest();
            let url = "https://api.hicandidate.com/v1/conversion_script_init?token=conv_script_token_20240501"
            url = url + "&" + localStorage.getItem("hic_conv_params") + "&source=" + location.href.split("?")[0]
            request.open("POST", url);
            request.send();
        } catch (e) {
            console.warn("HiCandidate conversion_script_init event submit failed:", e);
        }
        try {
            let request = new XMLHttpRequest();
            let url = "https://api.hicandidate.com/v1/get_clients_conversion_script_addons"
            url = url + "?token=conv_script_token_20260429"
            url = url + "&hic_jid=" + (new URL(location.href)).searchParams.get("hic_jid");
            request.open("GET", url);
            request.onreadystatechange = function () {
                if (request.readyState === 4) {
                    if (request.status === 200 ) {
                        try {
                            const data = JSON.parse(request.responseText);
                            data.forEach(function (item) {
                                if (item.javascript) {
                                    const script = document.createElement("script");
                                    script.textContent = item.javascript;
                                    document.documentElement.appendChild(script);
                                    script.remove();
                                }
                            });
                        } catch (error) {
                            console.error("Invalid JSON or JavaScript execution failed:", error, request.responseText);
                        }

                    } else {
                        console.error("Request failed:", request.status, request.responseText);
                    }
                }
            };
            request.send();
        } catch (e) {
            console.warn("HiCandidate conversion_script_init event submit failed:", e);
        }
    }
}();

function hic_conversion(conv_type = "") {
    if (localStorage.getItem("hic_conv_params")) {
        let request = new XMLHttpRequest();
        let url = "https://api.hicandidate.com/v1/conversion" + conv_type + "?token=conv_script_token_20240501"
        url = url + "&" + localStorage.getItem("hic_conv_params") + "&source=" + location.href.split("?")[0]
        request.open("POST", url);
        request.send();
    }
}
function hic_conversion2() {
    hic_conversion("2");
}
function hic_conversion3() {
    hic_conversion("3");
}

function hic_application_start() {
    hic_conversion();
}
function hic_application_finished() {
    hic_conversion("2");
}
function hic_quality_application() {
    hic_conversion("3");
}


