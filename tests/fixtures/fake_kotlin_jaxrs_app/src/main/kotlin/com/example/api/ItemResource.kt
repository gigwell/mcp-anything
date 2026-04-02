package com.example.api

import javax.ws.rs.*
import javax.ws.rs.core.MediaType

@Path("/api/items")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
class ItemResource {

    @GET
    fun listItems(@QueryParam("category") category: String?): List<Item> {
        return emptyList()
    }

    @GET
    @Path("/{id}")
    fun getItem(@PathParam("id") id: Long): Item {
        return Item()
    }

    @POST
    fun createItem(@QueryParam("name") name: String): Item {
        return Item()
    }

    @PUT
    @Path("/{id}")
    fun updateItem(@PathParam("id") id: Long, @QueryParam("name") name: String?): Item {
        return Item()
    }

    @DELETE
    @Path("/{id}")
    fun deleteItem(@PathParam("id") id: Long) {
    }

    // Edge case: Naked @GET with trailing comment on annotation
    @GET
    @RequestTimeout(1000) // load balancer health check
    fun getStatus(): Status {
        return Status()
    }

    // Edge case: Multiple annotations on single line
    @GET @Path("/health") @Timeout(5000) fun getHealth(): Health {
        return Health()
    }
}
