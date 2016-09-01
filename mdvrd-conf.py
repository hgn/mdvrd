{
    "common" : {
        "verbose" : "debug"
    },

    "interfaces" : [
        { "terminal_v4_addr" : "10.0.1.250", "local_v4_out_addr" : "10.0.1.1" },
        { "terminal_v4_addr" : "10.0.2.250", "local_v4_out_addr" : "10.0.2.1" },
    ],

    "ipc" : {
        "v4_listen_addr" : "127.0.0.1",
        "v4_listen_port" : "51337",
        "path" :           "/api/v1/route-update"
    }
}
