/* Offline local profile: no Nintendo network friends or presence sessions. */
static void friend_command(Message *m, uint32_t command, uint32_t session, int iface) {
    static unsigned reports;
    if (command != 2 || iface != D3_IF_FRIEND_NOTIFICATION || reports++ < 4)
        slog("friend iface=%d cmd=%u", iface, command);
    if (iface == D3_IF_FRIEND_CREATOR) {
        if (command > 1 || !m->domain) {
            unsupported_command(m, iface, command); return;
        }
        uint32_t object = domain_add(session, command == 0 ? D3_IF_FRIEND : D3_IF_FRIEND_NOTIFICATION);
        if (!object) { reply_service_result(m, D3_RESULT(121, 1)); return; }
        reply_domain_object(m, object); return;
    }
    DomainObject *object = &g_domain[m->domain_object - 1];
    if (command == 0) {
        if (!object->event) object->event = d3_handle_alloc(D3_OBJ_EVENT, "friend-event", 0);
        if (!object->event) { reply_service_result(m, D3_RESULT(121, 1)); return; }
        d3_event_set(object->event, 0);
        reply_domain_handle(m, object->event); return;
    }
    if (iface == D3_IF_FRIEND_NOTIFICATION) {
        if (command == 1) { d3_event_set(object->event, 0); reply_service_result(m, 0); }
        else if (command == 2) reply_service_result(m, D3_RESULT(124, 15));
        else unsupported_command(m, iface, command);
        return;
    }
    switch (command) {
    case 1: /* Cancel */
    case 10601: /* Close online session (none is open). */
    case 10610: /* Local presence, never published to a server. */
        reply_service_result(m, 0); return;
    case 10100: case 10101: case 10400: case 20100: case 20101:
        audio_reply(m, 0, 1); return;
    case 10120: case 10420: /* Cached network lists are unavailable. */
        audio_reply(m, 0, 1); return;
    default: unsupported_command(m, iface, command); return;
    }
}
